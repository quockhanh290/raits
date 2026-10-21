/* Áp lựa chọn font đã lưu, cho những trang KHÔNG nạp realtime.js.
 *
 * Ca thật: người dùng chọn IBM Plex trên /realtime, khoá được ghi vào
 * localStorage, nhưng /paper vẫn hiện Cascadia Mono — vì bảng ánh xạ
 * `html[data-font=...] → --font-ui` nằm trong realtime.css (mà /paper CÓ nạp),
 * còn đoạn đặt thuộc tính `data-font` lại nằm trong realtime.js (mà /paper
 * KHÔNG nạp). Nửa cơ chế có mặt, nửa kia không, và trang im lặng dùng font mặc
 * định — trông y như bộ đổi font hỏng.
 *
 * Khoá và tập giá trị phải khớp realtime.js. Mặc định theo thiết bị được
 * đặt ở đây trước first paint; realtime.js đọc lại data-font thay vì tự đoán.
 *
 * Nạp KHÔNG kèm `defer` để thuộc tính có mặt trước lượt vẽ đầu tiên; đặt sau
 * khi đã vẽ thì chữ nháy một nhịp đổi font.
 */
(() => {
  const FONT_KEY = 'raits-dashboard-font';
  const FONT_OPTIONS = new Set(
    ['cascadia', 'consolas', 'jetbrains', 'ibm-plex', 'lucida', 'courier', 'system']);
  /* Safari on current iPadOS can present itself as either iPad or MacIntel in
     desktop-site mode.  Use a bundled face only as that device's first default;
     an explicit choice in localStorage still wins on every platform. */
  const isIPad = /\biPad\b/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const platformDefault = isIPad ? 'ibm-plex' : 'cascadia';
  let saved = platformDefault;
  try { saved = localStorage.getItem(FONT_KEY) || saved; } catch (_) { /* tuỳ trình duyệt */ }
  document.documentElement.dataset.font = FONT_OPTIONS.has(saved) ? saved : platformDefault;
})();
