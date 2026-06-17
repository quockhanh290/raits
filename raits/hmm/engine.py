"""
RAITS HMM Engine
=================
The central regime-detection class.  Wraps hmmlearn's GaussianHMM with:

  - Section 3.1  State standardisation (Calm / Normal / Stress)
  - Section 3.2  Burn-in initialisation (backtesting + live deployment)
  - Section 3.3  Weekly retraining
  - Section 3.5  Label-switching safeguard (state sorting after every fit)
  - Persistence  Versioned model save/load with last-good-model fallback

Usage
-----
    from raits.hmm.engine import HMMEngine

    engine = HMMEngine()
    engine.fit(spy_close_series)            # initial training
    state = engine.predict_current(spy_close_recent)  # → 0 / 1 / 2
    label = engine.state_name(state)        # → "Calm" / "Normal" / "Stress"
    probs = engine.predict_proba(spy_close_recent)    # → array([p0, p1, p2])
"""

from __future__ import annotations

import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

from raits.hmm.features import build_feature_matrix
from raits.hmm.state_sorting import (
    HMM_STATES,
    sort_hmm_states, validate_state_order,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default hyperparameters
# ---------------------------------------------------------------------------

N_COMPONENTS = 4                   # Calm / Normal / Stress / Crisis
COVARIANCE_TYPE = "diag"           # Diagonal covariance — robust, sufficient for 3 features
N_ITER = 200                       # EM iterations
N_INIT = 10                        # Multiple random restarts (picks best log-L)
RANDOM_SEED = 42
TRAINING_LOOKBACK_DAYS = 252       # 1 year (Section 3.2)
MIN_VALID_LOG_LIKELIHOOD = -1e6    # Model validation threshold


# ---------------------------------------------------------------------------
# HMMEngine
# ---------------------------------------------------------------------------

class HMMEngine:
    """
    3-state Gaussian HMM for market regime detection.

    Parameters
    ----------
    n_components : int
        Number of hidden states (default 3 = Calm / Normal / Stress).
    covariance_type : str
        hmmlearn covariance type. Default "diag" — always PD, robust on small
        datasets. Use "full" only if you have 500+ training days and want to
        model within-state correlation between log_return and realised_vol.
    n_iter : int
        Maximum EM iterations.
    n_init : int
        Number of random restarts; best log-likelihood is kept.
    random_state : int
        RNG seed for reproducibility.
    model_dir : str or Path
        Directory for saving / loading versioned models.
    """

    def __init__(
        self,
        n_components: int = N_COMPONENTS,
        covariance_type: str = COVARIANCE_TYPE,
        n_iter: int = N_ITER,
        n_init: int = N_INIT,
        random_state: int = RANDOM_SEED,
        model_dir: str | Path = "models/hmm",
    ) -> None:
        self.n_components = n_components
        self.covariance_type = covariance_type
        self.n_iter = n_iter
        self.n_init = n_init
        self.random_state = random_state
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        self._model: Optional[GaussianHMM] = None
        self._last_good_model: Optional[GaussianHMM] = None
        self._trained_at: Optional[datetime] = None
        self._version: str = ""

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(
        self,
        spy_close: pd.Series,
        version_tag: str = "",
        save: bool = True,
    ) -> "HMMEngine":
        """
        Train the HMM on `spy_close` and sort states consistently.

        Internally runs `n_init` independent EM fits and keeps the one with
        the highest log-likelihood to avoid local optima.

        Parameters
        ----------
        spy_close : pd.Series
            Daily SPY close prices (oldest first).
        version_tag : str
            Optional tag appended to the saved model filename.
        save : bool
            Persist model to disk after fitting.

        Returns
        -------
        self  (for chaining)
        """
        logger.info(
            "HMM fit started: %d price observations, covariance=%s, n_init=%d",
            len(spy_close),
            self.covariance_type,
            self.n_init,
        )

        X = build_feature_matrix(spy_close)
        best_model = self._fit_best(X)
        sorted_model = sort_hmm_states(best_model)

        if not validate_state_order(sorted_model):
            logger.warning(
                "State variance ordering validation failed after sort — "
                "states may not be strictly Calm < Normal < Stress. "
                "Proceeding with best-effort sort."
            )

        # Promote to active model
        self._last_good_model = self._model  # keep previous as fallback
        self._model = sorted_model
        self._trained_at = datetime.now(timezone.utc)
        self._version = self._make_version(version_tag)

        self._log_model_summary()

        if save:
            self.save(self._version)

        return self

    def retrain(
        self,
        spy_close: pd.Series,
        version_tag: str = "",
        save: bool = True,
    ) -> bool:
        """
        Attempt to retrain and validate the new model before promoting it.

        If the new model fails validation (numerically unstable, log-likelihood
        below threshold), the existing model is kept and False is returned.

        Returns
        -------
        bool
            True if retrain succeeded and model was promoted; False on failure.
        """
        logger.info("HMM retrain initiated (version_tag='%s')", version_tag)
        try:
            X = build_feature_matrix(spy_close)
            new_model = self._fit_best(X)
            sorted_model = sort_hmm_states(new_model)

            if not self._validate_model(sorted_model, X):
                logger.warning(
                    "Retrain validation failed — keeping current model (v%s)",
                    self._version,
                )
                return False

            self._last_good_model = self._model
            self._model = sorted_model
            self._trained_at = datetime.now(timezone.utc)
            self._version = self._make_version(version_tag or "retrain")

            self._log_model_summary()

            if save:
                self.save(self._version)

            logger.info("HMM retrain successful → version %s", self._version)
            return True

        except Exception as exc:
            logger.error(
                "HMM retrain failed: %s — reverting to last good model", exc
            )
            if self._last_good_model is not None:
                self._model = self._last_good_model
                logger.info("Reverted to last good model (v%s)", self._version)
            return False

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict_sequence(self, spy_close: pd.Series) -> np.ndarray:
        """
        Viterbi-decode the most likely state sequence for the full price series.

        Parameters
        ----------
        spy_close : pd.Series
            Daily SPY close prices.

        Returns
        -------
        np.ndarray of int, shape (T,)
            State indices 0 (Calm), 1 (Normal), 2 (Stress) for each day.
        """
        self._require_fitted()
        X = build_feature_matrix(spy_close)
        return self._model.predict(X)

    def predict_current(self, spy_close_recent: pd.Series) -> int:
        """
        Predict the current regime from the most recent price history.

        Only the latest bar's state is returned (Viterbi over recent window).

        Parameters
        ----------
        spy_close_recent : pd.Series
            Recent daily SPY closes (at minimum 6 values so vol can be computed).

        Returns
        -------
        int  — 0 (Calm), 1 (Normal), or 2 (Stress)
        """
        self._require_fitted()
        X = build_feature_matrix(spy_close_recent)
        states = self._model.predict(X)
        return int(states[-1])

    def predict_proba(self, spy_close_recent: pd.Series) -> np.ndarray:
        """
        Return posterior state probabilities for the most recent bar.

        Uses the forward algorithm (scaled) for numerical stability.

        Returns
        -------
        np.ndarray of float, shape (3,)
            [P(Calm), P(Normal), P(Stress)] summing to 1.
        """
        self._require_fitted()
        X = build_feature_matrix(spy_close_recent)
        # predict_proba returns (T, n_states) — take last row
        posteriors = self._model.predict_proba(X)
        return posteriors[-1]

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def state_name(self, state_idx: int) -> str:
        """Map numeric state to label string."""
        return HMM_STATES[state_idx]

    def is_fitted(self) -> bool:
        return self._model is not None

    @property
    def model(self) -> Optional[GaussianHMM]:
        return self._model

    @property
    def trained_at(self) -> Optional[datetime]:
        return self._trained_at

    @property
    def version(self) -> str:
        return self._version

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, version: str = "") -> Path:
        """
        Pickle the fitted model to `model_dir`.

        File format: hmm_{version}.pkl
        """
        self._require_fitted()
        filename = f"hmm_{version or self._version}.pkl"
        path = self.model_dir / filename

        with open(path, "wb") as f:
            pickle.dump(
                {
                    "model": self._model,
                    "trained_at": self._trained_at,
                    "version": version,
                    "n_components": self.n_components,
                    "covariance_type": self.covariance_type,
                },
                f,
            )
        logger.info("HMM model saved → %s", path)
        return path

    def load(self, version: str) -> "HMMEngine":
        """
        Load a previously saved model from `model_dir`.

        Parameters
        ----------
        version : str
            The version tag used when saving (e.g. "20260301").

        Returns
        -------
        self
        """
        filename = f"hmm_{version}.pkl"
        path = self.model_dir / filename

        if not path.exists():
            raise FileNotFoundError(
                f"No saved model found at {path}. "
                "Check version tag or model_dir."
            )

        with open(path, "rb") as f:
            checkpoint = pickle.load(f)

        self._model = checkpoint["model"]
        self._trained_at = checkpoint.get("trained_at")
        self._version = checkpoint.get("version", version)
        logger.info(
            "HMM model loaded ← %s (trained %s)",
            path,
            self._trained_at,
        )
        return self

    def load_latest(self) -> "HMMEngine":
        """Load the most recently modified .pkl file in model_dir."""
        pkl_files = sorted(self.model_dir.glob("hmm_*.pkl"), key=lambda p: p.stat().st_mtime)
        if not pkl_files:
            raise FileNotFoundError(
                f"No HMM model files found in {self.model_dir}."
            )
        latest = pkl_files[-1]
        tag = latest.stem.replace("hmm_", "")
        return self.load(tag)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _fit_best(self, X: np.ndarray) -> GaussianHMM:
        """
        Run n_init independent GaussianHMM fits; return the best by log-L.
        """
        best_model = None
        best_log_prob = -np.inf

        rng = np.random.RandomState(self.random_state)

        for i in range(self.n_init):
            seed = rng.randint(0, 2**31 - 1)
            hmm = GaussianHMM(
                n_components=self.n_components,
                covariance_type=self.covariance_type,
                n_iter=self.n_iter,
                random_state=seed,
                verbose=False,
            )
            try:
                hmm.fit(X)
                log_prob = hmm.score(X)

                if log_prob > best_log_prob:
                    best_log_prob = log_prob
                    best_model = hmm

                logger.debug("Init %d/%d: log-prob=%.2f", i + 1, self.n_init, log_prob)

            except Exception as exc:
                logger.warning("HMM init %d failed: %s", i + 1, exc)
                continue

        if best_model is None:
            raise RuntimeError(
                f"All {self.n_init} HMM random initialisations failed. "
                "Check that feature data is valid and has sufficient variance."
            )

        logger.info(
            "Best initialisation: log-prob=%.2f (out of %d tries)",
            best_log_prob,
            self.n_init,
        )
        return best_model

    def _validate_model(self, model: GaussianHMM, X: np.ndarray) -> bool:
        """
        Basic numerical stability checks:
          1. Log-likelihood is finite and above floor.
          2. State variances are ordered (Calm < Normal < Stress) after sorting.
          3. Transition matrix rows sum to 1 (sanity).
        """
        try:
            log_prob = model.score(X)
        except Exception as exc:
            logger.warning("Model scoring failed during validation: %s", exc)
            return False

        if not np.isfinite(log_prob):
            logger.warning("Model log-likelihood is not finite: %s", log_prob)
            return False

        if log_prob < MIN_VALID_LOG_LIKELIHOOD:
            logger.warning(
                "Model log-likelihood %.2f below floor %.2f",
                log_prob,
                MIN_VALID_LOG_LIKELIHOOD,
            )
            return False

        if not validate_state_order(model):
            logger.warning("State variance ordering invalid after sort")
            # Non-fatal — allow but warn

        row_sums = model.transmat_.sum(axis=1)
        if not np.allclose(row_sums, 1.0, atol=1e-4):
            logger.warning("Transition matrix rows do not sum to 1: %s", row_sums)
            return False

        return True

    def _require_fitted(self) -> None:
        if self._model is None:
            raise RuntimeError(
                "HMMEngine has not been fitted yet. Call .fit() first."
            )

    def _make_version(self, tag: str = "") -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"{timestamp}_{tag}" if tag else timestamp

    def _log_model_summary(self) -> None:
        if self._model is None:
            return
        logger.info("─" * 60)
        logger.info("HMM Model Summary (version: %s)", self._version)
        for i in range(self.n_components):
            label = HMM_STATES[i]
            means = self._model.means_[i]
            cov = self._model.covars_[i]
            var_proxy = float(np.trace(cov)) if cov.ndim == 2 else float(np.sum(cov))
            logger.info(
                "  State %d (%s): μ=%s  var_trace=%.6f",
                i, label, np.round(means, 6), var_proxy,
            )
        logger.info("─" * 60)
