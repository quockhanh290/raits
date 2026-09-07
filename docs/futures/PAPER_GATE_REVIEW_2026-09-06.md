# Rà soát hệ thống chặn lệnh của Track 1

Ngày 2026-09-06. Commit `a3f8e43`.

Chỉ đọc. Không đóng cổng nào, không đặt cờ nào, không sửa file nào của hệ thống đang chạy.
Mọi thử nghiệm đều chạy trong bộ nhớ hoặc trên bản sao ở thư mục tạm.

Câu hỏi cần trả lời không phải "có nên chạy paper chưa" — đó là việc anh quyết.
Câu hỏi là: **khi hệ thống nói được hay không được, có tin nó không.**

---

## 1. Đo lại trạng thái nền

Chạy lệnh này ra đúng những gì đề bài ghi:

```
python -c "import sys;sys.path.insert(0,'.');from global_index import track1_gates as g; print(g.may_enable_orders()); print(g.self_check())"
```

Hệ thống trả lời: **không được đặt lệnh**. Ba cổng đang chặn: B1, cổng quan sát cây nến cuối
phiên, cổng bằng chứng shadow. Bộ tự kiểm trả về danh sách rỗng. Tất cả khớp đề bài.

**Ba chỗ trong đề bài cần sửa lại:**

Bản ghi mốc tài khoản đề bài ghi 194,0 giờ, nay đo ra 194,2 giờ. Đồng hồ chạy, bản ghi đứng
yên. Không sao cả, nhưng nhắc rằng con số trong một tài liệu cũng có hạn dùng.

Đề bài nói "có hai chỗ gọi cổng". Thật ra chỉ có một. Chỗ thứ nhất từ chối gửi lệnh thật.
Chỗ thứ hai chỉ ghi lại vào báo cáo là "nếu hỏi thì cổng trả lời gì" — nó không chặn gì cả.
Đếm nó vào làm ta tưởng cổng được cắm vào hai nơi, trong khi chỉ có một.

Đề bài viết `self_check()` trả rỗng rồi ghi "xem lớp khuyết tật 4", ngụ ý nó là loại kiểm tra
không biết kêu. Tôi thử phá và nó kêu. Xem mục 2.

---

## 2. Những chỗ đã kiểm và thấy tốt

Ghi ra để lần rà sau khỏi đi lại. Tất cả đều là đo, không phải đọc code rồi đoán.

**Bộ tự kiểm biết kêu.** Tôi phá tám luật của bảng cổng, mỗi lần một luật, ngay trong bộ nhớ
rồi trả lại nguyên trạng. Cả tám lần nó đều báo lỗi, và mỗi lần một câu khác nhau. Tám thứ tôi
phá: cổng trỏ tới một cờ không có thật; cổng trỏ tới một phép đo không có hàm nào đứng sau;
trạng thái lạ; cờ miễn trừ không phải cờ thật; cờ vừa mở cổng vừa miễn trừ chính phép đo của
cổng đó; cổng lẽ ra chỉ mở bằng phép đo mà lại cho mở bằng chữ ký; cổng phụ thuộc vào cổng
không tồn tại; cổng đã đóng mà vẫn còn chặn. Nên danh sách rỗng ở đây là kết quả thật, không
phải sự im lặng.

**Năm chỗ đọc bản ghi đều giữ cổng khi không thấy gì.** Tôi trỏ cả năm vào một thư mục rỗng.
Cả năm đều từ chối. Quan trọng hơn: mỗi cái nói lý do bằng lời riêng của nó — chưa có ngày nào
được chấm, chưa lần nào kiểm nhãn, chưa lần nào rà tài khoản, chưa có bản ghi mốc, chưa quan
sát được gì. Không cái nào trả lời "không thấy" thành "ổn". Đây đúng là kiểu lỗi từng làm mất
sáu slot vào lệnh, và ở đây không có.

**Chỗ kiểm đường lấy dữ liệu đi được cả hai chiều.** Tôi tự viết một file tạm lấy dữ liệu mà
không đi qua chỗ kiểm — nó giữ cổng và gọi tên file. Sửa file đó cho đi qua chỗ kiểm — nó mở
cổng. Hai kết quả đều tạo ra được theo ý muốn, không phải suy.

**Cổng bằng chứng shadow đóng lại được thật.** Tôi lấy đúng bằng chứng thật, chấm ở mốc "hôm
nay là 2026-10-15". Phép kiểm độ mới lật từ đạt sang hỏng. Cổng này tự nhận là "mở khi có bằng
chứng, đóng lại khi bằng chứng cũ đi", và tôi đã nhìn thấy nó làm đúng vậy.

**Bản ghi mốc tài khoản xử lý chuyện cũ-mới đúng cách.** 194,2 giờ so với hạn 24 giờ, nó đọc ra
"không xác định" và nói luôn lý do: giữa chừng tài khoản có thể bị reset hoặc bị giao dịch. Đây
là chuẩn tôi lấy làm thước cho mọi chỗ khác trong báo cáo.

**File xác nhận không mở he hé được cổng nào.** Gõ sai tên một khoá thì bị từ chối chứ không bị
bỏ qua. Điền sai kiểu dữ liệu thì bị từ chối. Miễn trừ mà không ghi lý do thì bị từ chối. Và chỉ
cần một lỗi là **cả file không cấp gì hết**, chứ không phải giữ phần đúng bỏ phần sai. File
không tồn tại thì không cấp gì, và đúng là không bị coi là lỗi.

**Chỗ chặn lệnh không tự tính lại phán quyết.** Nó gọi thẳng hàm liệt kê cổng đang chặn của bảng
đăng ký. Dashboard cũng vậy. Không có chuyện hai nơi tự tính ra hai câu trả lời khác nhau.

**Bộ thực thi từ chối ngay lúc tạo ra nó**, chứ không phải từ chối từng lệnh. Nên một bộ thực
thi chưa được cho phép thì không tồn tại để ai lỡ tay gọi. Và khi cổng còn đóng, đường gửi lệnh
không nạp lấy một file nào.

**Panel Track 1 không vẽ số liệu cũ.** Khi hỏi backend thất bại, nó thoát ra và nói "đầu đọc
không trả lời", kèm câu giải thích rằng đây là chuyện dashboard không hỏi được, không phải
chuyện tuyến có chạy hay không.

**Chốt chặn khởi động legacy có bắn hôm nay.** Vì quyết định B1 đã ký, một lần khởi động có
đăng ký 45 job vào lệnh của legacy trên cùng login bị chặn lại, kèm bốn lý do.

---

## 3. Những gì tìm ra

---

### F1. Một chốt chặn đang canh sai chỗ

**Ai sở hữu:** bộ test.
**Mức tin:** đã đo chắc chắn.

Có một phép kiểm với đúng một việc: xác nhận chưa có dấu vết lệnh nào xuất hiện. Nó kiểm hai
thứ — thư mục nhật ký lệnh, và cuốn sổ vị thế của Track 1.

Nửa sau nhìn sai chỗ. Nó tìm cuốn sổ **trong thư mục con**. Tuyến ghi cuốn sổ **ở thư mục
gốc**. Mà mọi thứ khác đều dùng thư mục gốc: điểm vào của slot, dòng lệnh của các job an toàn,
bộ đọc chấm điểm, và cả bảng hằng số của chính tuyến.

Cuốn sổ đã nằm ở chỗ thật từ **2026-09-04 lúc 13:57**, nặng 284 byte. Phép kiểm hôm nay vẫn
chạy xanh trong 0,95 giây.

```
chỗ phép kiểm đi tìm : d:\raits\global_index\live_positions.track1.json   không có  -> xanh
chỗ hệ thống thật ghi: d:\raits\live_positions.track1.json                CÓ        -> sẽ đỏ
```

Chỗ này đáng nói chứ không phải chuyện dọn dẹp, vì **đúng đường dẫn sai này đã được tìm ra và
sửa một lần rồi**. Bản sửa nằm ở bộ thực thi, và nó ghi rõ hậu quả hồi đó: một thành phần sinh
ra để đối chiếu vị thế của tuyến với broker đã đối chiếu một cuốn sổ **luôn luôn rỗng**, rồi
kết luận tuyến đang phẳng, bất kể nó thật sự giữ gì. Bản sửa đó chữa bằng cách **đọc hằng số
thay vì gõ lại đường dẫn**. Nhưng bộ test thì vẫn gõ lại. Bài học học được ở một file và không
sang được file kia.

Hôm nay sổ đang phẳng nên chưa có hậu quả gì. Vấn đề là **cái chuông không kêu được.**

Sửa thế nào: cho phép kiểm đọc đúng hằng số mà hệ thống đọc, đừng gõ lại đường dẫn.
Cái gì bắt được nếu lỗi quay lại: chính phép kiểm đó, sau khi sửa.
Bằng chứng nó sẽ đỏ: đã đo ở trên — trỏ vào đường dẫn thật thì nó đỏ ngay hôm nay.

---

### F2. Cổng quản việc VÀO lệnh. Nó không quản mọi lệnh Track 1 có thể gửi

**Ai sở hữu:** bộ lập lịch.
**Mức tin:** hành vi đã đo chắc chắn. Phần còn lại là một quyết định của anh, không phải một
phép đo.

Trong cả kho chỉ có đúng một dòng từ chối gửi lệnh vì bảng đăng ký nói không. Đường đó đi từ
điểm vào, qua module gửi, tới bộ thực thi. Khi cổng đóng, module gửi thậm chí không nạp file
nào. Đường đó sạch.

**Nhưng còn một đường thứ hai tới broker.** Ở chế độ chỉ chạy Track 1, bộ lập lịch bật thêm hai
job bảo vệ của riêng Track 1: một job thoát khi giữ quá hạn, và một lượt quét sửa lệnh dừng
theo giờ. Hai job này là chương trình thật, có kết nối, có đặt lệnh. **Chúng không hỏi bảng
đăng ký.**

Cái quyết định chúng có làm gì hay không là **cuốn sổ vị thế** — sổ rỗng thì chúng thoát ra
trước khi kết nối. Chúng dùng sổ riêng, file dừng riêng, khoá riêng, client id riêng.

Gần như chắc chắn đây là cố ý, và hợp lý. Nếu việc sửa lệnh dừng ngừng chạy ngay khi cổng vào
lệnh đóng, thì một vị thế đang mở sẽ nằm đó không ai bảo vệ — tệ hơn hẳn thứ mình đang tránh.
Thiết kế lộ rõ: hai bộ an toàn, hai cuốn sổ, hai file khoá, hai client id, hai dấu "hôm nay đã
chạy", mỗi thứ có lý do viết sẵn.

Nhưng câu **"bảng đăng ký quyết định Track 1 có được gửi lệnh hay không"** thì không đúng như
đang viết. Ai tin câu đó sẽ hiểu sai vào đúng ngày đầu tiên tuyến giữ một vị thế. Câu đúng phải
là: **bảng đăng ký quyết định Track 1 có được MỞ vị thế mới hay không. Thứ nó đang giữ thì vẫn
được bảo vệ, cổng đóng hay mở không đổi.**

Hôm nay sổ đang phẳng, và hai job này chỉ bật ở chế độ chỉ chạy Track 1. Nên chưa có gì. Rủi ro
bắt đầu vào ngày cuốn sổ không còn phẳng.

**Quyết định anh cần ra, và cái giá của từng lựa chọn:**

Đường bảo vệ có nên hỏi gì trước khi kết nối không? Ba hướng đều hợp lý, tôi không chọn hộ.

- **Không hỏi gì**, giữ như hiện tại. Giá: phải viết lại câu mô tả ở mọi chỗ nó xuất hiện, và
  người vận hành phải nhớ rằng cổng đóng không có nghĩa là broker im.
- **Cho nó một công tắc dừng riêng.** Tuyến đã có sẵn file dừng riêng. Giá: phải có người quyết
  xem dừng việc sửa lệnh dừng có bao giờ an toàn hơn không. Thường là không.
- **Xét xem cuốn sổ ở đâu ra.** Chỉ hành động trên cuốn sổ do lệnh đã qua cổng tạo ra. Giá: đây
  mới là câu hỏi thật nằm dưới, và trả lời không rẻ.

Câu hỏi thứ ba đáng nói thẳng dù hôm nay chưa khai thác được. Cuốn sổ do **bộ khởi tạo của
tuyến** ghi, chứ không chỉ bộ thực thi ghi. Nên trên nguyên tắc, sổ có thể mang vị thế mà không
lệnh nào qua cổng sinh ra, và hai job bảo vệ sẽ đặt lệnh thật lên broker cho những vị thế đó.
Trong cách nối dây hiện tại không có gì làm việc này, và tôi **không dựng được** một đường như
vậy nếu không chạy những thứ bản rà soát này không được phép chạy. **Nên câu này ghi là: chưa
ai kiểm.**

---

### F3. Cổng được miễn trừ và cổng được đo hiện ra giống hệt nhau

**Ai sở hữu:** bảng đăng ký, và dashboard.
**Mức tin:** đã đo chắc chắn.

B1 gồm hai nửa: một quyết định phải ký, và một sự thật phải đo. Có một cờ miễn trừ, dành cho
ngày broker thật sự không hỏi được.

Cờ đó được làm tốt. Tự nó không mở gì cả — vẫn phải có một trong hai quyết định thật được ghi.
Và bật nó mà không viết lý do thì bị từ chối.

File hiện tại **đã ký, chưa miễn trừ**. Đúng trạng thái nên có.

Vấn đề nằm ở phía sau. Tôi copy file xác nhận ra thư mục tạm, thêm cờ miễn trừ vào bản copy
(file thật không đụng), rồi đo:

```
file thật   : đã ký                     -> B1 CÓ trong danh sách chặn
bản copy    : đã ký + miễn trừ           -> B1 BIẾN MẤT khỏi danh sách chặn
cả hai lần  : phép đo bắt buộc vẫn báo CHƯA ĐẠT
```

Nghĩa là: B1 được miễn trừ để lại danh sách chặn **y hệt** B1 đã được đo. Và sổ cái không phân
biệt được. Nó công bố danh sách **các cờ có thể có**, chứ không bao giờ công bố **các cờ đang
được bật**. Người đọc phải tự để ý rằng một cổng biến mất khỏi danh sách chặn trong khi phép đo
của nó vẫn báo chưa đạt, rồi **tự suy ra** là có miễn trừ. Suy từ chỗ mâu thuẫn.

Backend của dashboard làm tốt hơn — nó có dựng hẳn thông tin này. Nó đi đâu thì xem F4.

Sửa thế nào: công bố cả các cờ **đang bật**, không chỉ các cờ có thể có. Và ghi lại với mỗi cổng
nó được mở bằng cách nào: chữ ký, phép đo, hay miễn trừ.
Cái gì bắt được nếu lỗi quay lại: chính bộ tự kiểm, thêm một luật — cổng nào có cờ miễn trừ thì
phải báo được lý do mở.
Bằng chứng nó sẽ đỏ: **chưa lấy được**, vì trường đó chưa tồn tại. Đây là đề xuất duy nhất trong
báo cáo mà tôi chưa dựng được bằng chứng đỏ. Nên nó ghi là *đề xuất*, không phải *phát hiện*.

---

### F4. Dashboard dựng sẵn phần B1 mà không ai nhìn thấy

**Ai sở hữu:** giao diện dashboard.
**Mức tin:** đã đo chắc chắn.

Backend lắp sẵn một khối thông tin B1 khá đầy đủ: quyết định đã ghi chưa, file có nhưng hỏng
hay không, ai ký, ký lúc nào, **phép đo có bị miễn trừ không**, trạng thái phép đo, tuổi tính
theo giờ, và hạn của nó. Chính tài liệu của nó nói vì sao thêm vào: trước đây người vận hành
phải rời khỏi trang mới biết được tình trạng cái cổng quan trọng nhất của tuyến.

Tôi tìm khắp trang realtime và trang thế hệ mới xem chỗ nào **đọc** khối đó. **Không có chỗ
nào.** Trang có ba chỗ nhắc tới B1, cả ba đều là câu bình luận hoặc tên hiển thị của cổng. Khối
đó được tính lại mỗi lượt hỏi và không vẽ ra đâu cả.

Nối vào F3: **trên màn hình, cổng mở vì được miễn trừ và cổng mở vì đã đo là cùng một hình ảnh
— cái chip biến mất.** Sự phân biệt được dựng ở backend rồi dừng lại ngay đó.

Cùng chỗ này còn một cái nữa. Bảng tên hiển thị của các cổng là bảng **gõ tay** và có bốn dòng.
Bảng đăng ký có **năm** cổng chặn lệnh. Cái thiếu chính là **cổng quan sát cây nến cuối phiên —
cổng đang chặn hôm nay**. Nên nó hiện ra dưới dạng chuỗi chữ hoa thô, còn hai cổng chặn kia hiện
ra thành câu đọc được. Không giấu gì, nhưng một danh sách gõ tay trôi khỏi danh sách tự quét
đúng là kiểu lỗi mà bảng đăng ký né được nhờ tự đi tìm lấy file của mình.

Sửa thế nào: vẽ khối B1 ra. Và làm sao để một cổng chưa có tên thì **hiện ra là chưa có tên**,
chứ không âm thầm rơi vào phương án dự phòng.
Cái gì bắt được nếu lỗi quay lại: một phép kiểm trang, khẳng định mọi cổng mà bảng đăng ký có
thể đưa vào danh sách chặn đều có tên hiển thị, và khối B1 có lên tới màn hình.
Bằng chứng nó sẽ đỏ: có ngay hôm nay, không cần sửa gì — bảng tên đang thiếu một cổng đang
chặn, nên phép kiểm đó đỏ trên trang hiện tại.

---

### F5. Dòng quan trọng nhất đầu trang không kiểm xem số liệu còn mới không

**Ai sở hữu:** giao diện dashboard.
**Mức tin:** đã đo chắc chắn.

Dải trạng thái đầu trang mang thứ mà chính lời bình luận trong code gọi là **sự thật vận hành
lớn nhất của trang**: tuyến có đặt được lệnh không, và cổng nào đang chặn.

Khi hỏi backend thất bại, trang **giữ lại số liệu cũ** và gắn thêm một dấu lỗi. Panel Track 1
xử lý đúng — nó thoát ra và nói đầu đọc không trả lời. **Dải trạng thái thì không.** Nó đọc
thẳng số liệu còn sót lại từ lượt trước, không kiểm dấu lỗi. Trong cả file, chỗ duy nhất có
kiểm dấu lỗi đó là dòng hiển thị cuốn sổ.

Hai chiều đều sai, theo hai kiểu:

- Lần trả lời cuối là *không đặt được lệnh* → dải vẫn khẳng định một điều nó không còn nhìn
  thấy được nữa.
- Lần trả lời cuối là *đặt được lệnh* → điều kiện của dải chỉ kiểm đúng giá trị "không", nên
  giá trị "có" còn sót lại làm **không có dòng nào hiện ra cả**. Trang im lặng đúng về cái mà
  dải này sinh ra để nói.

Chiều thứ hai hôm nay chưa xảy ra được vì cổng chưa bao giờ mở. Nó thành thật vào đúng ngày cổng
mở.

Sửa thế nào: cho dải kiểm cùng dấu lỗi mà panel kiểm, và nói "hiện không hỏi được" thay vì nhắc
lại câu trả lời cũ.
Cái gì bắt được nếu lỗi quay lại: một phép kiểm trang, ép lượt hỏi thất bại rồi xem dải có nói
là nó không hỏi được không.
Bằng chứng nó sẽ đỏ: phép kiểm đó đỏ trên trang hiện tại.

---

### F6. Một phép đo không cổng nào dùng tới

**Ai sở hữu:** bảng đăng ký.
**Mức tin:** đã đo chắc chắn.

Bảng phép đo có sáu mục. Tôi duyệt hết mọi cổng xem cổng nào gọi phép đo nào: **năm** cái được
dùng. Cái thứ sáu — cái hỏi tài khoản có đang phẳng không — **không cổng nào gọi tới**. Nó bị
thay thế khi yêu cầu của B1 mở rộng từ "tài khoản có phẳng không" thành "tuyến này có sở hữu
login này không". Cái cũ bị bỏ lại trong bảng.

Bộ tự kiểm không bắt được, và về cấu trúc thì không thể bắt: mọi luật của nó đi từ cổng ra phép
đo, không có luật nào đi ngược từ phép đo về hỏi "có cổng nào cần tôi không".

Vì sao không chỉ là chuyện dọn dẹp: cái đó là code chạy được đầy đủ, có tài liệu cẩn thận giải
thích rằng vắng mặt không phải là đạt, bản ghi cũ cũng không phải là đạt. Ai rà soát bằng cách
đọc bảng sẽ **đếm ra sáu phép kiểm đang sống. Chỉ năm cái chạy.**

Sửa thế nào: hoặc xoá, hoặc nối vào. Đừng để lửng.
Cái gì bắt được nếu lỗi quay lại: bộ tự kiểm, thêm chiều ngược — mọi phép đo trong bảng phải có
ít nhất một cổng gọi tên.
Bằng chứng nó sẽ đỏ: đã đo — áp luật đó vào bảng hôm nay thì nó trả về đúng cái phép đo mồ côi,
trong khi bộ tự kiểm hiện tại trả rỗng.

---

### F7. Phép kiểm độ mới chỉ chặn một đầu

**Ai sở hữu:** phần chấm điểm sẵn sàng.
**Mức tin:** trong hàm thì đã đo chắc chắn. Nhưng **chưa có bằng chứng** là thực tế chạm tới
được.

Tuổi bằng chứng tính bằng một phép trừ ngày, rồi so với hạn 21 ngày. Đo tại biên:

```
bản ghi 2026-08-16, hôm nay 2026-09-06   tuổi  21   còn mới -> ĐÚNG   (chuẩn, sát mép)
bản ghi 2026-08-15, hôm nay 2026-09-06   tuổi  22   còn mới -> SAI    (chuẩn, quá mép)
bản ghi 2026-12-31, hôm nay 2026-09-06   tuổi -116  còn mới -> ĐÚNG   (bản ghi ở TƯƠNG LAI đọc ra là còn mới)
```

Một bản ghi mang ngày tương lai thì lọt qua. So với chuẩn mà bản ghi mốc tài khoản đặt ra — nơi
một bản ghi ngoài hạn đọc ra "không xác định" và nói rõ lý do — thì phép kiểm này chỉ có **một**
thanh chắn.

Sau đó tôi kiểm xem có gì sinh ra được bản ghi như vậy không. Vì một lỗi không ai chạm tới được
là việc gia cố, không phải lỗ hổng. Ngày trong bản ghi được ghi bằng giờ miền Đông. Phép kiểm
cũng đọc "hôm nay" bằng giờ miền Đông. Hai bên khớp nhau. Và đồng hồ máy thì **chạy sau** giờ
miền Đông chứ không chạy trước. **Nên không có bằng chứng nào cho thấy đường ghi bình thường
sinh ra được ngày tương lai.**

Ngày ghi hỏng không đọc được thì sao? Chỗ phân tích ném lỗi, và phép kiểm bao ngoài biến mọi lỗi
thành một lời từ chối. Đã kiểm, đúng chiều an toàn.

Báo cáo vì chỗ mất cân đối này có thật và vá thì rẻ, không phải vì nó đang gây hại.

---

### F8. Hai bản ghi không đối chiếu được với nhau, và một cặp thứ hai chưa ai nói tới

**Ai sở hữu:** cấu trúc của các bản ghi.
**Mức tin:** phần danh tính tài khoản là **chưa ai kiểm**. Bảng đăng ký tự nói ra điều đó, và
nói đúng.

Phép kiểm bằng chứng của B1 đối chiếu những gì quyết định khẳng định với những gì đã ghi lại.
Và nó **báo rõ một mệnh đề là chưa kiểm**: bản rà B1 không ghi mã tài khoản, nên bản rà và bản
ghi mốc tài khoản không đối chiếu chéo được với nhau.

Câu đó **đúng**. Tôi kiểm năm bản ghi thật, trải bốn ngày. Phần broker của bản rà ghi: nguồn,
có kết nối không, quan sát lúc nào, danh sách vị thế, lệnh đang treo, và **số vốn**. Không có mã
tài khoản, ở bản nào cả. Đây không phải do bản ghi hiện tại đang cũ.

Bảng đăng ký xử lý đúng: mệnh đề đó được ghi là CHƯA KIỂM, và không tính vào nhóm đã đạt. Một
phép so sánh không có khoá chung thì không thể hỏng vì đúng lý do — và cái này nói thẳng ra
điều đó thay vì giả vờ.

**Nhưng có một chỗ chưa ai nói tới.** Bản ghi mốc tài khoản **chép lại** phán quyết B1 vào trong
nó — trạng thái, mã, diễn giải. Nhưng không ghi là **chép từ bản ghi B1 nào**, cũng không có mốc
thời gian riêng cho bản chép đó. Nên nếu một bản ghi mốc được viết dựa trên một bản rà B1 cũ,
**không có gì phát hiện ra**. Đó là cặp thứ hai không nối được với nhau, và khác cặp thứ nhất,
cặp này không được khai báo ở đâu.

Hai bản này còn đủ gần để trông như nối được. Ngày 2026-08-27, bản rà ghi vốn 250.819,13 và bản
ghi mốc ghi 250.817,91 — cùng tài khoản, cách nhau vài phút. **Vốn là cái khoá trông hấp dẫn và
là cái khoá tồi**, vì nó chạy liên tục. Dùng nó làm khoá sẽ là sửa sai.

Sửa thế nào: cho chỗ đọc tài khoản ghi lại mã tài khoản, và cho bản ghi mốc ghi lại nó đã đọc
bản rà B1 nào. Khi đó mệnh đề đang ghi là chưa kiểm sẽ thành mệnh đề **có thể hỏng**.
Cái gì bắt được nếu lỗi quay lại: chính phép kiểm bằng chứng của B1 — nhánh báo lệch **đã viết
sẵn**, hiện đang không chạm tới được.
Bằng chứng nó sẽ đỏ: lịch sử của chính nhánh đó, và bảng đăng ký có ghi lại. Một phiên bản
trước so hai trường mà **không bản ghi nào có**. Nên cả hai mệnh đề là điều kiện không bao giờ
bắn, mà đọc lên thì như phép kiểm đã đạt. Nó bị bắt bằng cách in diễn giải ra và nhận ra hai
mệnh đề **không sinh ra chữ nào**.

---

### F9. Lằn ranh cần canh ba file, nhưng chỉ canh được một

**Ai sở hữu:** bộ test.
**Mức tin:** đã đo chắc chắn.

Có một quy tắc an toàn: không cổng nào, không phép chấm sẵn sàng nào, không bộ chấm điểm nào
được phép nhắc tới cái module chứa dữ liệu dựng lại. Phép kiểm duyệt qua ba file và **assert
trên từng file ngay trong vòng lặp**. Nên file vi phạm đầu tiên làm vòng lặp dừng, và hai file
sau không được kiểm nữa.

Đây không phải tôi tự nghĩ ra. Nó **đã được ghi trong kho**, kèm phép đo làm nó lộ ra: khi có
một chỗ nhắc trong bảng đăng ký, hai file kia "không còn được duyệt tới". Ghi chú nói thẳng:
một cái chuông cho ba file mà chỉ kêu cho một file thì bằng với tắt hẳn.

Bản sửa sau đó dời dữ liệu sang kho riêng, nhờ vậy gỡ được chỗ nhắc vi phạm. Đó là bản sửa tốt
hơn thật, vì nó thay một bộ lọc bằng một sự tách biệt về cấu trúc. **Nhưng vòng lặp thì chưa bao
giờ được sửa.** Nó vẫn assert bên trong vòng. Cái tính chất khiến một chỗ nhắc che mất hai file
**vẫn còn nguyên**. Chỉ có chỗ nhắc là đã mất. Đưa lại một chỗ nhắc thì kiểu che lấp đó quay về.

Sửa thế nào: gom kết quả cả ba file rồi assert một lần trên cả tập.
Cái gì bắt được nếu lỗi quay lại: chính phép kiểm đó, sau khi sửa.
Bằng chứng nó sẽ đỏ: phép đo đã ghi ở trên chính là bằng chứng. Đúng kịch bản này, đã xảy ra một
lần trong chính kho này.

---

### F10. Hai câu mô tả một chuyện đã qua

**Ai sở hữu:** tài liệu của bộ thực thi, và phần trợ giúp của công cụ vận hành.
**Mức tin:** đã đo chắc chắn.

Hai chỗ này chỉ quan trọng vì chúng định hình điều người vận hành **tin** về cái cổng.

Chỗ thứ nhất. Cái hàm đi hỏi bảng đăng ký trên đường gửi lệnh tự mô tả là nó trả lời "trong
trạng thái chưa có xác nhận nào được cấp, và đó là trạng thái duy nhất nó từng ở". Câu đó **hết
đúng** từ khi bảng đăng ký bắt đầu tự đọc file xác nhận. Và một xác nhận đã ký nằm trên đĩa từ
2026-08-27. Hành vi thì đúng. Câu mô tả thì sai — mà lại sai ở đúng chỗ đang cưỡng chế.

Chỗ thứ hai. Công cụ vận hành ghi trong phần trợ giúp rằng chế độ khởi động shadow "từ chối trừ
khi có file dừng và **không có** file xác nhận". Tôi đo: file xác nhận **đang tồn tại**, và chốt
chặn trả về danh sách từ chối **rỗng** ở chế độ chỉ chạy Track 1. Luật thật hẹp hơn và tốt hơn —
nó chỉ từ chối khi file xác nhận tồn tại **và** mọi cổng chặn lệnh đều đã thông. Dòng trợ giúp
hứa một lời từ chối **không xảy ra**. Đó là chiều gây hiểu lầm.

Sửa thế nào: suy hai câu đó ra từ điều code thật sự hỏi, hoặc xoá hẳn mệnh đề kể lại.
Cái gì bắt được nếu lỗi quay lại: chính thói quen của bảng đăng ký, áp vào đây. Nhiều cổng trong
đó **cố ý từ chối kể lại tình trạng của cổng khác**, đúng vì những câu như thế đã trôi khỏi sự
thật hai lần rồi. Kỷ luật đó đang thiếu ở hai chỗ này.

---

### F11. Không ai đối chiếu số ngày có bản ghi với lịch giao dịch

**Ai sở hữu:** phần chấm điểm sẵn sàng.
**Mức tin:** trong code thì đã xác minh. **Chưa có bằng chứng** là nó đã gây hại.

Cổng bằng chứng shadow đòi 5 ngày chấm được, không ngày nào hỏng. Nó đếm những ngày **đã có bản
ghi**. Nó không hỏi ngày nào **đáng lẽ phải có** mà không có.

Tôi tìm khắp phần chấm điểm, phần chấm ngày và bộ đọc dashboard xem có chỗ nào so số ngày có
bản ghi với lịch giao dịch: **không có chỗ nào.**

Cơ chế: một ngày không chạy thì không sinh bản ghi. Không bản ghi thì không có gì để chấm hỏng.
Nên **một ngày biến mất trông y hệt một ngày chưa tới**, và đồng hồ đếm 5 ngày sạch đứng lại mà
không có gì đỏ lên.

**Hôm nay chưa có ngày nào mất.** Ngày giao dịch gần nhất là thứ Sáu 04/09 và nó có đủ bằng
chứng, gồm cả 22 slot NKD. Thứ Bảy 05/09 và Chủ nhật 06/09 không có bằng chứng, và đó là đúng.

Ghi lại vì chính lượt rà này đã vấp: tôi đọc thấy 05/09 trống, kết luận là một ngày giao dịch bị
mất, và viết ra một phát hiện sai — trong khi đó là thứ Bảy. Không có gì trong hệ thống nói được
"ngày này không phải ngày giao dịch" hay "ngày này đáng lẽ phải có". Người đọc phải tự tra lịch,
và tự tra thì tự sai.

Sửa thế nào: nói rõ ngày nào là ngày giao dịch, ngày nào không, và báo ngày thiếu như một sự
kiện riêng — không gộp vào "hỏng", vì một ngày không chạy khác một ngày chạy mà hỏng.
Cái gì bắt được nếu lỗi quay lại: chính phép kiểm đó.
Bằng chứng nó sẽ đỏ: chưa dựng được hôm nay, vì hiện không có ngày giao dịch nào thiếu. Dựng
được bằng cách chấm một cây lịch có một ngày thường bị bỏ trống.

---

### F12. Lượt chấm buổi tối chấm lại ngày cũ bằng đồng hồ mới, và nó tha bổng

**Ai sở hữu:** bộ chấm điểm phiên.
**Mức tin:** đã đo chắc chắn. **Đã xảy ra thật**, ngày 03/09.

Mỗi ngày có **hai** lượt chấm: một lượt sáng, một lượt tối. Lượt sau ghi đè lượt trước, vì bản
ghi cuối cho mỗi cặp (phạm vi, sleeve, ngày) là bản có hiệu lực.

Sleeve NKD chạy khung 01:10–02:55 rạng sáng. Để biết ngày đó có chấm được không, bộ chấm hỏi:
scheduler đã chạy trước khi cửa sổ mở chưa? Nhưng nó lấy **lần khởi động gần nhất**, chứ không
phải lần khởi động đang có hiệu lực với cửa sổ của ngày đang chấm. Nếu scheduler được khởi động
lại sau 02:55 — chuyện bình thường — thì lượt chấm buổi tối thấy một lần khởi động muộn hơn cửa
sổ và kết luận **không slot nào từng đến hạn**.

Đo trên ngày 03/09, hai lượt chấm cùng một sleeve:

```
lượt sáng  07:05  scheduler khởi động 02/09 21:13 (TRƯỚC cửa sổ)  -> FAIL
                  lý do: độ phủ không đủ, thiếu slot — quan sát 20 trên 22
lượt tối   20:15  scheduler khởi động 03/09 03:31 (SAU cửa sổ)    -> CHƯA ĐỦ DỮ LIỆU
                  lý do: "scheduler khởi động 03:31 — SAU khi cửa sổ đóng lúc 02:55;
                          không slot nào từng đến hạn"
                  nhưng CHÍNH bản ghi đó ghi: quan sát 20 trên 22
```

Bản ghi **tự mâu thuẫn trong cùng một dòng**: nó nói không slot nào từng đến hạn, đồng thời ghi
20 slot đã quan sát được. Và bản thắng là bản sai, chỉ vì nó mới hơn.

Kiểm chéo bằng bản ghi tín hiệu — thứ do chính đường slot ghi ra, không qua bộ chấm:

```
26,27,28/08 · 31/08 · 01,02/09   22/22 slot, tất cả không tín hiệu   -> NKD chạy đúng
03/09                            20/22 slot                          -> thiếu 2 slot, có thật
04/09                            22/22, 19 bị từ chối                -> ngày đang chặn
```

Nên chuyện thiếu 2 slot ngày 03/09 là **có thật**, lượt chấm sáng bắt đúng, và lượt chấm tối
xoá nó đi. Bản chấm cấp ngày cho 03/09 chỉ có lượt tối, và nó ra ĐẠT.

**Vì sao đây là chuyện của cổng, không phải chuyện của NKD.** Cổng bằng chứng shadow đòi 5 ngày
không ngày nào hỏng, và nó đọc bản chấm **cuối**. Cơ chế trên biến một ngày hỏng thành một ngày
"chưa đủ dữ liệu", và "chưa đủ dữ liệu" thì không bị đếm là hỏng. Nghĩa là **cổng đang được nuôi
bằng dữ liệu đã được làm mềm**, và chiều làm mềm luôn là chiều tha bổng — chưa bao giờ ngược lại,
vì khởi động lại chỉ có thể muộn hơn cửa sổ, không thể sớm hơn.

Repo đã trả giá cho đúng họ lỗi này một lần và có ghi lại: chấm ngày hôm qua bằng đồng hồ hôm
nay, rồi báo một cửa sổ đã đóng là vẫn còn mở. Bản sửa hồi đó cho phép truyền mốc "bây giờ" vào.
Mốc **khởi động scheduler** thì không được sửa cùng.

Sửa thế nào: chấm một ngày phải dùng lần khởi động đang có hiệu lực với cửa sổ của ngày đó, chứ
không dùng lần khởi động gần nhất. Và một bản ghi vừa nói "không slot nào đến hạn" vừa ghi số
slot đã quan sát lớn hơn không thì phải bị từ chối, không được ghi ra.
Cái gì bắt được nếu lỗi quay lại: một luật bất biến trong chính bộ chấm — số slot quan sát được
lớn hơn 0 thì mâu thuẫn với kết luận "không slot nào từng đến hạn".
Bằng chứng nó sẽ đỏ: có sẵn trên đĩa — bản ghi NKD ngày 01, 02 và 03/09 đều vi phạm luật đó.

---

### F13. Lý do "khớp một phần không xảy ra" thuộc về đường cũ, không thuộc Track 1

**Ai sở hữu:** đường đặt lệnh của Track 1.
**Mức tin:** con số đã đo chắc chắn. Hệ quả trên Track 1: **chưa ai kiểm**.

Bản rà runner xếp lỗi "khớp một phần" vào diện để lại, với lý do đo được: mỗi lệnh chỉ một hợp
đồng, mà lệnh thị trường một hợp đồng thì không thể khớp một phần. Lý do đó đúng — cho đường cũ.
Hằng số một hợp đồng nằm trong điểm vào của đường cũ.

**Track 1 không đi qua đó.** Sleeve Stress của nó gửi **7 hợp đồng MNQ**, và số lượng đó đi trên
chính các dòng tín hiệu chứ không lấy từ một hằng số. Lớp dịch sang lệnh môi giới nói thẳng: số
lượng là của ứng viên. Một lệnh thị trường 7 hợp đồng **hoàn toàn có thể khớp một phần**.

Nên tiền đề giữ cho lỗi đó ở mức "để lại" **không mở rộng sang Track 1 được**. Không phải vì có
ai sai — bản rà runner nói về runner, và nói đúng. Chỉ là câu kết luận đã được mang sang một
đường khác mà tiền đề của nó thì không theo sang.

**Track 1 hiện làm gì với một lần khớp một phần?** Đo được:

- Nó **ghi** số đã khớp vào nhật ký lệnh, và **phân loại riêng** trạng thái khớp một phần. Cả
  hai đều có, và đó là nửa tốt.
- **Không chỗ nào so số đã đặt với số đã khớp.** Tìm khắp mọi tệp của tuyến: số đã khớp được
  ghi, được kiểm không âm, được dùng làm số mong muốn khi đọc lại từ môi giới — không nơi nào
  đặt nó cạnh số đã gửi đi.
- Bộ thực thi **không chạm vào sổ vị thế**; bên gọi mới tiến sổ, và chỉ khi có xác nhận khớp.
  Nhưng đường từ lần khớp tới sổ tới lệnh dừng **chưa tồn tại đầy đủ** — lệnh dừng ở đây mới là
  ý định, chưa gửi.

Vì đường đó chưa đủ, **không thể nói Track 1 mang lỗi ấy, và cũng không thể nói nó không mang.**
Nhãn đúng là chưa ai kiểm — và nó cần được kiểm trước lệnh thật đầu tiên, không phải sau, vì
kết cục của lỗi ấy ở đường cũ là một vị thế ngược chiều không có gì bảo vệ.

Cùng câu hỏi, cùng trạng thái, cho lỗi "mã chưa khai vẫn chạy một hợp đồng": tiền đề của nó cũng
là mọi mã đều bằng một, và Track 1 cũng không thoả tiền đề đó.

Cách kiểm, và nó không cần môi giới thật: đưa cho bộ thực thi một môi giới giả trả về khớp một
phần — đặt 7, khớp 3 — rồi hỏi sổ ghi mấy, và lệnh dừng kế tiếp sẽ đặt theo số nào.
Bằng chứng phép kiểm đó sẽ đỏ: chưa dựng được, vì đường từ lần khớp tới lệnh dừng chưa nối xong.
Đó chính là lý do phải kiểm lúc nối, chứ không phải lúc chạy.

---

### F14. Mười phép kiểm ghim "chưa ai ký" thành bất biến, và chữ ký đã có

**Ai sở hữu:** bộ test.
**Mức tin:** đã đo chắc chắn.

Chạy sáu bộ kiểm quanh đường đặt lệnh: **12 đỏ, 276 xanh**. Mười trong 12 cái đỏ có cùng một
nguyên nhân — chúng khẳng định tệp xác nhận **không tồn tại**:

```
assert not Path(REPO / "track1_go_live_confirmation.json").exists()
E   AssertionError: assert not True
```

Tệp ấy được ký ngày 27/08. Việc ký là **tiến triển bình thường của dự án**, không phải hồi
quy — nhưng các phép kiểm viết trước ngày đó đã đóng băng trạng thái "chưa ai ký" thành một
bất biến. Ý định của chúng đúng và đáng giữ: không có gì được tự tạo ra tệp ấy. Cách viết thì
không phân biệt được "không ai tạo nó" với "người vận hành đã cố ý ký".

Vì sao đáng báo: một bộ kiểm lúc nào cũng có 12 dòng đỏ là bộ kiểm người ta học cách bỏ qua,
và đỏ thứ 13 — cái thật — sẽ chìm vào đó. Cùng họ với một báo động không bao giờ tắt.

Sửa thế nào: ghim điều thật sự cần ghim — **không tiến trình nào tự ghi tệp ấy trong lượt chạy
này** — thay vì ghim rằng nó chưa từng tồn tại. Ví dụ so thời điểm sửa tệp trước và sau, hoặc
khẳng định nội dung không do phép kiểm sinh ra.
Bằng chứng bản sửa đó cần: chính 10 dòng đỏ hôm nay là bằng chứng cách viết cũ không phân biệt
được hai chuyện.

---

### F15. Phần sửa đã làm trong lượt này

Ba việc được giao. **Một xong, hai bị chặn**, và lý do bị chặn là luật chứ không phải kỹ thuật.

**XONG — số đã đặt nay nằm cạnh số đã khớp (F13).**

Nguyên nhân đo ra sạch hơn dự đoán. Nhật ký lệnh **đã có sẵn** một trường cho số hợp đồng của
dòng, và tài liệu của trường nói đúng lý do nó tồn tại: số ấy "trước đây chỉ ngụ ý trong lệnh
và mất trên đường vào nhật ký, khiến một lần khớp một phần không thể đối chiếu với ý định."
Trường có, mục đích ghi rõ, **và không ai điền**. Đo trước bản sửa, gửi 7 khớp 3:

```
nhật ký ghi:  filled_qty = 3     qty = 0        (ba hợp đồng trên không có gì)
```

Bản sửa: một dòng, điền từ chính lệnh, đặt ở chỗ dựng bản ghi nên **mọi trạng thái** đều mang
kích thước — kể cả dòng ý định chưa ai trả lời, thứ làm cho một kết cục KHÔNG BIẾT có kích
thước để ước lượng rủi ro.

Phép kiểm mới: 6 mục, xanh. Đã chứng minh đỏ được bằng cách gỡ bản sửa **trong bộ nhớ**, hai
kiểu gỡ:

```
gỡ hẳn (trạng thái trước bản sửa)          5 đỏ / 1 xanh
lấy số đã đặt từ kết quả trả về thay vì
từ lệnh (phần thiếu luôn bằng 0)           4 đỏ / 2 xanh
```

Kiểu gỡ thứ hai đáng kể: nó là bản sửa sai trông giống bản sửa đúng, và nếu không có phép kiểm
neo vào NGUỒN của con số thì nó qua được.

Không gây hồi quy: sáu bộ kiểm quanh đường đặt lệnh cho **12 đỏ / 276 xanh trước bản sửa và
12 đỏ / 276 xanh sau** — cùng danh sách. 12 đỏ ấy là món nợ có sẵn, xem F14.

**KHÔNG CÒN VIỆC — hai mục kia đã được sửa từ trước.** Tôi đề xuất chúng vì tin trạng thái ghi
trong bản rà vòng hai. Đo code hiện tại thì cả hai đã xong và đã ở HEAD:

- dòng nhật ký đối chiếu tài khoản **đã** in cả hai vế, và cổng so phần dư với ngưỡng rồi phát
  cảnh báo cũng đã có đủ. Comment trong code nói đúng điều tôi định nêu: dòng ấy là thứ làm cho
  phép đo kế tiếp trở nên khả thi, còn ngưỡng thì giữ nguyên cho tới khi có phép đo đó. Việc
  còn lại thuần là **hiệu chuẩn**, cần dữ liệu mới, không code được.
- đường đóng lệnh không lấy được bản ghi khớp **đã** điền ngày phiên và gắn cờ "ngày ra là ước
  lượng", kèm chú thích mô tả đúng cái bẫy "đã book, đã ghi, vẫn vô hình".

48 dòng chưa commit trong tệp runner không đụng tới cả hai; chúng chỉ về nhãn tuyến trên dòng
giao dịch. Bài học cho chính bản rà này: **một bản rà là ảnh chụp lúc viết nó.** Trạng thái ghi
trong đó đọc như hiện tại, và không phải vậy. Việc còn thật sự thiếu là **dựng lại phép kiểm**
cho đường ấy — script đo cũ không còn trên đĩa, nên hiện không có gì canh bản sửa.

**XONG — một lần chạy là một thẻ, và job dùng chung có nhóm của nó (F17).**

Bộ đọc nhật ký job nay quét một lượt trước để biết nhãn nào khởi chạy tiến trình con, và chỉ mở
thẻ một-dòng cho nhãn **không** khởi chạy gì. Dòng phụ của nhãn có khởi chạy được gắn vào chẩn
đoán của chính thẻ đó — trước bản sửa chúng thành thẻ, sau bản sửa chúng vẫn còn chữ, chỉ nằm
đúng chỗ. Đo trên nhật ký thật của ngày hôm nay:

```
trước:  5 thẻ   (3 cho job SPY: 22s thật + hai thẻ 0s)
sau :   3 thẻ   (1 cho job SPY, 22s, hai dòng kia thành chẩn đoán của nó)
```

Và tuyến nay có **ba** nhóm thay vì hai, quyết ở nơi biết câu trả lời chứ không suy trên trang.
Nhóm dùng chung được **đo** chứ không phân theo cảm tính: chế độ chỉ-Track-1 bỏ hẳn 45 job, và
cả 45 đều là slot của tuyến cũ — không job nào trong nhóm dùng chung nằm trong đó. Một phép kiểm
ghim đúng quan hệ ấy, nên thêm nhầm một nhãn vào nhóm dùng chung sẽ đỏ.

Phép kiểm mới: 18 mục, xanh. Đỏ được, ba kiểu gỡ trong bộ nhớ:

```
gỡ lượt quét trước (trạng thái cũ)              4 đỏ
quay lại hai nhóm                               6 đỏ
gọi mọi thứ không-Track-1 là dùng chung         5 đỏ
```

Kiểu thứ ba đáng kể: nó là bản sửa quá tay trông giống bản sửa đúng, và thứ bắt được nó là phép
kiểm đối chiếu với danh sách bộ lập lịch thật sự bỏ — tức neo vào phép đo, không vào ý kiến.
Đối chứng cũng được ghim: một nhãn chỉ ghi một dòng và không khởi chạy gì **vẫn phải có thẻ**,
vì nhánh ấy sinh ra cho đúng những nhãn đó.

Hồi quy: 225 và 27 phép kiểm của hai bộ dashboard đều xanh sau bản sửa.

**Kết cục ở trang: ô chip được GỠ HẲN, không phải sửa lại.**

Tôi sửa nó trước — cho ô đọc tuyến từ dữ liệu, thêm nhóm thứ ba dùng lại đúng chữ "CẢ HAI
TUYẾN" mà tệp ấy đã chọn cho một ô khác. Rồi chủ dự án chỉ ra điều kiện đã đổi, và đo thì đúng:

```
45 slot chiến lược của tuyến cũ   KHÔNG còn được đăng ký (bỏ hẳn, không phải bị hãm)
cuốn sổ của tuyến cũ              0 vị thế, không đổi từ 04/09
```

Không còn tuyến thứ hai để phân biệt với, nên ô ấy đang trả lời một câu hỏi không ai còn hỏi.
Và cái việc nó từng làm thì tên job nay tự làm: hàng của tuyến cũ hiện tên thô
`STOP_REPAIR_SUN_1830`, hàng Track 1 hiện "Track 1 stop-repair sweep 18:30".

**Dữ liệu thì giữ.** Bộ đọc vẫn ghi tuyến của từng job vào payload, và phép kiểm vẫn ghim nó
vào chính danh sách bộ lập lịch bỏ đi. Bỏ một ô khỏi màn hình khác với bỏ một sự thật khỏi hồ
sơ — nếu có ngày cần vẽ lại, con số nằm sẵn đó, và cho tới lúc ấy phép kiểm vẫn bắt được ai
xếp nhầm một job vào nhóm dùng chung.

Về việc chạm vào tệp trang: những thay đổi chưa commit của việc khác nằm từ dòng 1944 trở đi
và nói về trục giá với nhãn mức của biểu đồ; vùng tôi sửa là 1552–1567. Không chồng lấn. Luật
là không sửa chồng lên việc của người khác, không phải không mở tệp họ đang mở.

**Một thứ còn lại, và nó là câu hỏi chứ không phải lỗi.** Slot chiến lược của tuyến cũ đã biến
mất và sổ của nó rỗng, nhưng **các job an toàn của tuyến ấy vẫn được đăng ký và vẫn chạy** —
lượt quét 18:30 chiều nay là một trong số đó. Chúng canh một cuốn sổ không còn gì để canh. Giữ
chúng là quyết định đúng khi sổ còn vị thế đang cạn; giờ sổ đã rỗng hai ngày. Gỡ chúng khỏi
lịch là việc của chủ dự án, không phải của bản rà này, nhưng nếu câu "mọi thứ giờ phục vụ Track
1" đúng thì đây là chỗ nó chưa đúng.

Mục "mã chưa khai vẫn chạy một hợp đồng" nằm trong tệp runner, cùng chờ. Bản sửa số hợp đồng ở
trên **không** chạm tới nó — nói ra vì hai mục này dễ bị coi là một.

---

### F16. Hai thứ cùng tên "chế độ", và mỗi cuối tuần chúng nói ngược nhau

**Ai sở hữu:** giao diện dashboard.
**Mức tin:** đã đo chắc chắn. **Không phải sự cố** — không chặn gì cả.

Trên màn hình, ô chế độ hiện **"Not measured"**, trong khi cổng kiểm nhãn của bảng đăng ký báo
**ĐẠT**. Cả hai đều đúng, vì chúng là hai đại lượng khác nhau mang cùng một cái tên:

```
NHÃN chế độ       nhãn HMM gán cho phiên gần nhất
                  ghi lần cuối: thứ Sáu 04/09 13:47 ET   tuổi 55,6h   hạn 48h   -> KHÔNG XÁC ĐỊNH
KIỂM nhãn         so nhãn lịch sử xem có xê dịch không
                  chạy lần cuối: Chủ nhật 06/09 16:00     1.761 nhãn, không nhãn nào đổi -> ĐẠT
```

Ô trên trang đọc **nhãn**; cổng đọc **kiểm nhãn**. Nhãn rỗng thì ô in "Not measured".

**Vì sao job SPY cuối tuần chạy mà ô vẫn trống.** Job ấy chạy Chủ nhật 18:00 ET, và hôm nay nó
chạy sạch: phát hiện chuỗi SPY mới tới 03/09 trong khi cửa sổ đêm nay cần 04/09, lấy về, rồi tự
báo là đã phục hồi. Nó cập nhật chuỗi SPY và chạy phép kiểm nghiêm — tức nó ghi **bản ghi KIỂM
NHÃN**. Nó **không** ghi một **NHÃN mới**: nhãn chỉ sinh ra khi một phiên chạy, và cuối tuần
không có phiên nào.

Nói thêm cho rõ vì câu hỏi đặt ra đúng chỗ này: job SPY ấy **không thuộc tuyến cũ**. Nó là hạ
tầng dùng chung, và nó tồn tại chính vì sleeve Nikkei — cửa sổ Nikkei mở tối Chủ nhật, nên dữ
liệu SPY của thứ Sáu phải có mặt trước đó. Chế độ chỉ-Track-1 giữ lại đúng nhóm job route-trung
tính này.

**Và cuối tuần nào cũng vậy, theo cấu trúc.** Nhãn cuối cùng của tuần được ghi chiều thứ Sáu;
slot Nikkei đầu tiên chạy 01:10 ET sáng thứ Hai. Đo khoảng cách:

```
nhãn cuối    Fri 2026-09-04 13:47 ET
slot đầu     Mon 2026-09-07 01:10 ET
cách nhau    59,4 giờ            hạn 48 giờ
```

Một cửa sổ đếm bằng **giờ đồng hồ liên tục** áp lên một chuỗi chỉ cập nhật vào **ngày giao
dịch**. Cuối tuần dài hơn cửa sổ, nên ô ấy đỏ mỗi tuần một lần dù không có gì hỏng.

**Không chặn gì, đã kiểm.** Bản ghi nhãn chỉ được đọc bởi bộ lập lịch, bởi chính nó, và bởi lớp
hiển thị — không đường ra quyết định nào của slot đọc nó. Đối chứng: thứ Hai 31/08 ở đúng tình
huống này, và Nikkei hôm đó chạy đủ 22 trên 22 slot, chấm ĐẠT.

Nên đây là chuyện đọc màn hình, không phải chuyện an toàn. Nhưng nó là một ô đỏ **không bao giờ
tắt vào cuối tuần**, và một cảnh báo có lịch cố định là cảnh báo người ta học cách bỏ qua — rồi
lần nó đỏ vì lý do thật sẽ trông y hệt.

Sửa thế nào: hoặc đếm tuổi bằng **phiên giao dịch** thay vì giờ đồng hồ, hoặc để ô ấy nói được
"chưa tới phiên mới" khác với "nhãn cũ bất thường". Và tách tên: một ô là *nhãn*, một ô là *đã
kiểm nhãn chưa* — hiện cả hai đều hiện ra dưới chữ "regime".
Bằng chứng bản sửa cần: khoảng 59,4 giờ ở trên lặp lại mỗi tuần và không cần dựng.

---

### F17. Một lần chạy hiện thành ba thẻ, hai trong đó chạy 0 giây

**Ai sở hữu:** bộ đọc nhật ký job.
**Mức tin:** đã đo chắc chắn.

Job SPY cuối tuần chạy **một lần** hôm nay. Trang hiện **ba thẻ**: một cái 22 giây, hai cái 0
giây. Nhật ký thật, sáu dòng, từ 16:00:00 đến 16:00:22:

```
16:00:00  cảnh báo — chuỗi dữ liệu mới tới 03/09, cần 04/09 trước cửa sổ đêm nay
16:00:00  câu lệnh sắp chạy
16:00:22  hoàn tất OK
16:00:22  ĐÃ PHỤC HỒI — 04/09 đã về
```

Bộ đọc trả về đúng ba thẻ, và đo được từng cái:

```
22:00:00 -> 22:00:00   0s   lý do: "chuỗi dữ liệu mới tới 03/09..."     <- thẻ giả
22:00:00 -> 22:00:22  22s   lý do: không có                             <- lần chạy thật
22:00:22 -> 22:00:22   0s   lý do: "ĐÃ PHỤC HỒI — 04/09 đã về"          <- thẻ giả
```

**Cơ chế.** Bộ đọc có một nhánh mở-rồi-đóng-ngay một thẻ cho bất kỳ dòng mang nhãn job nào
không phải câu lệnh khởi chạy, không phải "bỏ qua", không phải "hoàn tất OK". Nhánh ấy được
thêm vì lý do đúng: có những job chỉ ghi đúng một dòng rồi thôi, và trước đó chúng không hiện
lên ở đâu cả — kể cả lượt chạy mọi thứ đều tốt, là lượt người vận hành cần thấy nhất.

Nhưng nhánh ấy **không phân biệt được** "job chỉ ghi một dòng" với "một dòng phụ của job ghi
nhiều dòng". Điều kiện chặn duy nhất là *chưa có thẻ nào đang mở* — mà dòng cảnh báo đến TRƯỚC
câu lệnh, và dòng phục hồi đến SAU khi "hoàn tất OK" đã đóng thẻ. Cả hai đều lọt.

**Hai chiều nói sai, và đều theo hướng dễ chịu.** Cả hai thẻ giả mang trạng thái *hoàn tất*.
Một cái mang câu "dữ liệu còn thiếu" — tức lý do job cần chạy — mà hiện ra như một lần chạy đã
xong. Cái kia mang câu báo tin tốt, cũng thành một lần chạy đã xong.

**Hệ quả đếm được.** Dòng tóm tắt đầu panel nói *"5 trên 5 lượt hoàn tất"*. Thực tế có **ba**
lần chạy: quét sửa lệnh dừng của tuyến cũ, quét của Track 1, và job SPY. Con số lượt chạy đang
bị thổi lên, và nó là con số đầu tiên người vận hành đọc.

Sửa thế nào: chỉ mở thẻ một-dòng khi nhãn ấy **không** có dòng khởi chạy nào trong cùng lượt —
tức quyết định sau khi đã đọc hết các dòng của nhãn đó, chứ không quyết ngay tại dòng đang đọc.
Những dòng phụ nên đi vào phần chẩn đoán của thẻ thật, chỗ chúng vốn thuộc về.
Bằng chứng bản sửa cần: chính ba thẻ hôm nay — sau khi sửa phải còn một, kéo dài 22 giây, mang
cả hai câu kia làm chẩn đoán.

**Về chip "LEGACY" trên ba thẻ đó.** Lần tìm đầu tôi bỏ cuộc sớm và ghi là không truy ra được.
Sai: tôi chỉ tìm chữ viết hoa, mà trang viết hoa bằng kiểu dáng chứ không bằng nội dung. Tìm lại
thì nó là một dòng, ở hàm dựng chip tuyến cho mỗi thẻ:

```
loại job không mang tiền tố track1_  ->  gắn chip TUYẾN CŨ
```

Hai nhóm, và nhóm thứ hai suy ra **bằng loại trừ**. Job SPY không mang tiền tố Track 1, nên
thành tuyến cũ — trong khi hai job SPY tồn tại **vì** sleeve Nikkei của Track 1: cửa sổ Nikkei
mở tối Chủ nhật, nên dòng SPY của thứ Sáu phải nằm trên đĩa trước đó, và tên hai job ấy nói
thẳng là "trước NKD".

Ý định gốc của chip thì đúng và hẹp: vài job bảo trì chạy theo cặp, một lượt mỗi tuyến, cùng
một phút, nên hai hàng cùng giờ đọc như bản sao nếu không có gì nói tuyến. Nhưng cách viết là
"không phải Track 1 thì là tuyến cũ", và hạ tầng dùng chung không có chỗ trong hai nhóm đó — nó
bị gán cho đúng cái tuyến nó ít liên quan nhất.

Bộ lập lịch đã vạch lằn ranh này và nói ra: chế độ chỉ-Track-1 được mô tả là "Track 1 cộng hạ
tầng dùng chung", và khối gỡ việc của tuyến cũ giữ lại "cổng 13:45, nhịp tim, bản lùi của báo
cáo phiên" với lý do cả ba trung tính về tuyến. Khái niệm có ở bộ lập lịch và dừng lại ở đó.

---

### F18. Mười một lượt quét của tuyến cũ sẽ gọi mọi vị thế Track 1 là "mồ côi"

**Ai sở hữu:** lịch chạy của bộ lập lịch.
**Mức tin:** cơ chế đã đọc hết đường code; **chưa xảy ra** vì Track 1 chưa giữ vị thế nào.

Câu hỏi đặt ra là các lượt quét của tuyến cũ có phục vụ Track 1 không. Đo ra hai nửa, và
chúng ngược nhau.

**Nửa yên tâm: chúng KHÔNG chạm vào vị thế Track 1.** Bước đặt lại lệnh dừng cho vị thế trần
duyệt danh sách đọc từ **sổ của chính nó**, rồi mới lọc thêm điều kiện môi giới cũng xác nhận.
Sổ của tuyến cũ rỗng, nên danh sách rỗng, nên bước ấy không làm gì. Tôi đã ngờ ngược lại — rằng
một lượt quét của tuyến cũ có thể đặt lệnh dừng lên vị thế Track 1 theo mức của nó — và đọc hết
đường code thì không phải vậy. Nói ra vì suýt nữa thành một báo động sai.

**Nửa còn lại: chúng NHÌN THẤY vị thế Track 1, và sẽ kêu.** Bước đối chiếu chạy trước đó so
danh sách vị thế môi giới trả về với sổ của chính nó, và môi giới **không lọc theo tuyến** —
đó là toàn bộ nội dung của B1: một login là một sổ vị thế. Nhánh cuối của phép so ấy:

```
với mỗi vị thế môi giới báo mà sổ không có:
    CRITICAL "B3 ORPHAN: IBKR có <mã> <chiều> x<n> mà không có mục nào khớp trong file
              — vị thế mở ngoài runner này?"
```

Ngày đầu tiên Track 1 giữ một vị thế, mỗi lượt quét của tuyến cũ sẽ in đúng dòng đó. **Mười
lượt một ngày**, cộng lượt thoát quá hạn. Và bộ lập lịch nâng mọi dòng CRITICAL của tiến trình
con thành sự cố, nên nó không dừng ở tệp log — nó lên bảng điều khiển.

Câu chữ của cảnh báo còn hướng người đọc đi sai: "vị thế mở ngoài runner này?" là câu hỏi đúng
khi chỉ có một tuyến. Giờ câu trả lời là *"đúng, tuyến kia mở, và đó là chuyện bình thường"* —
nhưng dòng cảnh báo không biết tuyến kia tồn tại.

**Nên trả lời cho câu hỏi ban đầu là: chúng liên quan tới Track 1, nhưng không phục vụ Track 1.**
Chúng không bảo vệ được vị thế Track 1 — lưới an toàn của Track 1 là mười một job riêng của nó,
canh sổ riêng. Chúng chỉ nhìn thấy vị thế ấy và báo nhầm.

Cộng với những gì đã đo: 45 slot chiến lược của tuyến cũ không còn được đăng ký, và sổ của nó
giữ 0 vị thế không đổi từ 04/09, còn bản rà tài khoản sáng nay báo môi giới có 0 vị thế và 0
lệnh đang treo.

**Đây là lý do gỡ mạnh hơn hẳn lý do tiết kiệm kết nối.** Không gỡ thì ngày Track 1 mở vị thế
đầu tiên cũng là ngày bảng điều khiển đỏ mười lần, vì một tuyến đã nghỉ hưu báo động về vị thế
của tuyến đang chạy. Và đó đúng là ngày người vận hành cần bảng điều khiển nói thật nhất.

Quyết định là của chủ dự án. Điều bản rà này thêm được là: nó có hạn, và hạn ấy là lệnh đầu
tiên chứ không phải một lúc nào đó.

---

### F19. Bảng lịch hỏi sàn chứng khoán Mỹ, còn tuyến này giao dịch trên CME

**Ai sở hữu:** bảng lịch của trang.
**Mức tin:** đã đo chắc chắn. **Đã sửa** trong lượt này.

Bảng lịch trên trang hỏi một hàm mà docstring của chính nó viết: *"True nếu NYSE mở"*. Tuyến
này không giao dịch cổ phiếu Mỹ — các sleeve là hợp đồng tương lai chỉ số trên CME, và một
trong số đó là Nikkei.

Hai lịch trùng nhau ngày thường và tách nhau đúng vào ngày lễ Mỹ. Đối chiếu với số thanh dữ
liệu Nikkei đã lưu:

```
Labor Day 2023 / 2024 / 2025    CME mở,  NYSE đóng,   672 / 860 / 596 thanh
Thanksgiving 2025               CME mở,  NYSE đóng,   431 thanh
Good Friday 2024 / 2025         cả hai đóng,            0 thanh
```

Ngày 07/09/2026 là Labor Day. Bộ lập lịch nổ **92 job** vì cron của nó chỉ biết thứ trong
tuần; bảng lịch báo **0 slot**. Nên trang chỉ ra công việc kế tiếp trễ nguyên một ngày, và
không có dòng nào cho bất cứ thứ gì thật sự chạy.

**Bản sửa đầu tiên của tôi sai, và đáng ghi lại.** Tôi cho bảng lịch dùng đúng luật của cron —
ngày trong tuần thì có slot. Một phép kiểm có sẵn đỏ ngay, và nó đúng: Good Friday là ngày
trong tuần và CME đóng thật, nên luật ấy sẽ bịa ra nguyên một ngày slot trễ hạn. Hai luật, mỗi
cái sai đúng vào những ngày cái kia đúng. Câu hỏi cần một cuốn lịch, không phải một cái đồng hồ.

Kết cục: thư viện lịch sàn thành phụ thuộc thật, và một hàm hỏi CME đứng **cạnh** hàm hỏi
NYSE chứ không thay nó — lịch chứng khoán vẫn đúng việc của nó, vì SPY không có giá vào ngày
lễ Mỹ và cổng độ tươi cần biết điều đó. Đã kiểm thư viện không đổi thứ gì đang được tin: câu
trả lời về NYSE trùng khít luật viết cứng suốt 120 ngày tới, không một khác biệt.

Sót một chỗ ở lần sửa đầu, và câu hỏi của chủ dự án moi ra: cờ "hôm nay có phải ngày giao dịch"
nằm ngay hai dòng trên bảng lịch vẫn hỏi NYSE. Nửa bản sửa còn tệ hơn không sửa — hai con số
mâu thuẫn trong cùng một gói dữ liệu và không ai biết cái nào sai.

Một dòng cố ý để lệch chứ không uốn cho khớp: Good Friday 2026 lịch nói đóng mà dữ liệu có 359
thanh. Uốn luật cho vừa một dòng thì không vừa dòng nào khác.

---

### F20. Đồng hồ trên cùng của panel là đồng hồ của một tuyến đã chết

**Ai sở hữu:** giao diện dashboard.
**Mức tin:** đã đo chắc chắn. **Đã sửa** trong lượt này.

Panel tên là "Source Clocks" — sáu dòng trả lời "dữ liệu trên trang này mới tới đâu". Dòng
trên cùng đọc tệp trạng thái mà runner của tuyến cũ ghi ra. Tệp ấy sửa lần cuối **24/08 00:58**
và sẽ không bao giờ đổi nữa, vì tuyến ấy đã ngừng giao dịch.

Giá trị không sai, và nó có nhãn "tuyến cũ, đã nghỉ hưu" để người đọc không tưởng là số hôm
nay. Nhưng nó trả lời câu *"runner quan sát lần cuối khi nào"* bằng số của runner **không
chạy**, trong khi runner **đang chạy** thì không có dòng nào trên panel. Và nó chiếm đúng chỗ
mắt nhìn trước nhất.

Đây là cái thứ tư cùng một dạng trong một buổi: một ô trỏ vào nguồn của tuyến cũ sau khi tuyến
mới đã tiếp quản. Ba cái trước là nhãn tuyến trên thẻ công việc, bảng lịch hỏi sai sàn, và mười
một lượt quét canh một cuốn sổ rỗng. Không cái nào là lỗi logic; tất cả là **một mô tả ở lại
sau khi thứ nó mô tả đã đi**.

Bản sửa cho dòng ấy đọc ngày cuối cùng tuyến đang chạy ghi đo thời gian slot — thứ chỉ được
viết khi một slot thật sự chạy xong, đúng như tệp cũ chỉ được viết khi runner cũ chạy xong.
Đồng hồ cũ không bị bỏ: nó xuống một dòng riêng, giữ nhãn, và chỉ hiện khi đã cũ — bỏ hẳn thì
mất khả năng thấy tuyến cũ có bất ngờ sống lại hay không.

---

## 4. Trả lời tám lớp khuyết tật của đề bài

| Lớp | Kết luận |
|---|---|
| 1 — chỗ kiểm hỏng theo chiều mở | **Không có ở năm chỗ đọc bản ghi.** Cả năm giữ cổng khi không thấy gì, và đều nói lý do. Có một khe hở về cấu trúc: một file trên tuyến mà cú pháp hỏng sẽ làm chỗ kiểm đường lấy dữ liệu **ném lỗi** thay vì trả lời, và lỗi đó chạy ra tới lệnh gọi cổng ngoài cùng. Mọi nơi nhận nó thì hoặc sập trước khi gửi được gì, hoặc bắt lại thành lời từ chối — nên vẫn nghiêng về khoá lại. Nhưng "tôi không biết" đang được nói ra bằng một cú sập chứ không bằng một câu trả lời. Cách đó chỉ cách chỗ mong manh một lần refactor. |
| 2 — tính ra mà không cắm vào | **Một khe hở thật, F2.** Đường vào lệnh đúng là chỉ có một và đúng là có cổng. Đường bảo vệ là con đường thứ hai tới broker và nó không hỏi bảng đăng ký, theo thiết kế. Ghi chú "BROKEN" trong module quan sát là **đã cũ** — nó mô tả một lỗi đã sửa xong bằng cách dời dữ liệu đi. Thứ còn sống sót từ nó là F9. |
| 3 — miễn trừ đè lên phép đo | **Cơ chế miễn trừ được làm tốt, và vô hình.** F3, F4. |
| 4 — bộ tự kiểm không nói được | **Đã giải oan bằng phép đo.** Tám lần phá, tám lỗi khác nhau. Rỗng ở đây là bằng chứng. Điểm mù của nó là chiều ngược lại, F6. |
| 5 — cổng chỉ đi một chiều | **Đã kiểm cả hai chiều** cho chỗ kiểm đường dữ liệu và cho cổng bằng chứng shadow, bằng cách tạo ra từng kết quả. **Chưa kiểm** cho cổng quan sát cây nến cuối phiên và cổng kiểm nhãn chế độ. Cả hai hôm nay bị giữ vì *chưa có bản ghi nào*, và cú chuyển ra khỏi trạng thái đó chưa ai nhìn thấy. |
| 6 — cũ-mới bị gộp thành đạt/hỏng | **Bản ghi mốc tài khoản đặt ra chuẩn và đạt chuẩn đó.** Tìm được một chỗ mất cân đối, F7, và chưa có bằng chứng nó chạm tới được. |
| 7 — hai bản ghi không có khoá chung | **Đúng, và bảng đăng ký tự khai báo.** Cộng thêm một cặp thứ hai chưa khai báo, F8. |
| 8 — dashboard trôi khỏi sổ cái | **Bản thân phán quyết KHÔNG trôi.** Trang chở đúng câu trả lời của bảng đăng ký chứ không tự tính lại, và panel từ chối vẽ câu trả lời cũ. Thứ trôi là mọi thứ xung quanh: cờ miễn trừ không tới nơi, khối B1 không ai đọc, một cổng không có tên, và dải trạng thái không kiểm số liệu còn mới hay không. F4, F5. |

---

## 4b. Trạng thái hệ thống, đo lại 2026-09-07 12:20 ET

Thêm vào cuối phiên, sau khi các bản sửa đã vào và một phiên ngày lễ đã chạy qua.

### Con số quan trọng nhất

```
687 slot đã chạy trong 11 ngày
  0 slot ra tín hiệu vào lệnh
598 không có tín hiệu
 89 bị từ chối
```

Từ vựng trạng thái **có** chỗ cho "tìm thấy tín hiệu thô" và "tín hiệu được nhận trong
shadow". Không ngày nào chạm tới. Thư mục nhật ký lệnh rỗng; sổ vị thế giữ 0.

**Nên toàn bộ bằng chứng tích luỹ được là bằng chứng về HẠ TẦNG, không phải về CHIẾN LƯỢC.**
Hệ đã chứng minh nó chạy đúng giờ, lấy được dữ liệu, ghi được bằng chứng, chấm được điểm.
Nó **chưa chứng minh** được nó ra quyết định đúng, vì chưa có quyết định nào để xét.

Cổng bằng chứng shadow đòi năm ngày không hỏng. Nó **không** đòi ngày nào có kèo. Nên khi
cổng mở, câu nó nói là *"hạ tầng chạy sạch năm phiên"* — và người đọc rất dễ hiểu thành
*"chiến lược đã được kiểm chứng"*. Hai câu ấy cách nhau rất xa, và không có gì trên màn
hình phân biệt chúng.

### Độ ổn định

```
53x  bất đồng ở phần chồng lấn   26-27/08 và 04/09 — ánh xạ hợp đồng, đã sửa
22x  cổng chặn                    26-27/08 — chặn đúng việc
14x  không có nguồn bar           26-27/08 — nguồn chưa nối
```

Từ 28/08 đến 03/09 **không một lần từ chối nào**, rồi 19 lần ngày 04/09 do roll hợp đồng,
rồi 07/09 sạch hoàn toàn. Đường cong đi đúng hướng.

### Cái mới được chứng minh hôm nay

Phiên 07/09 là **lần đầu tuyến này đi qua một ngày lễ**. Nikkei 22/22 sạch. Trước hôm nay
đây là ô "chưa ai chạy qua", và nó là ô đã làm bảng lịch nói sai suốt vì hỏi nhầm sàn.

### Cái còn chưa ai chạm

Đường gửi lệnh **chưa bao giờ chạy** — không phải "chạy và bị từ chối", mà là chưa có quyết
định nào để gửi. Bộ thực thi, nhật ký lệnh, đối chiếu vị thế, lệnh dừng: có code, có phép
kiểm, chưa cái nào gặp một lệnh thật.

### Điều đáng lo nhất, và nó không nằm trong cổng nào

Trong một buổi, **bảy chỗ trên bảng điều khiển** hoá ra đang mô tả tuyến đã nghỉ hưu hoặc
dùng luật đã hết đúng. Không cái nào là lỗi logic.

Điều đó nói hai chuyện. Một: hệ này thay đổi nhanh hơn tốc độ các mô tả của nó được rà lại.
Hai: **cả bảy đều tìm ra vì có người nhìn màn hình và thấy lạ**, không phải vì phép kiểm nào
bắt. Phép kiểm kiểm kê ở F17 bắt được cái thứ tám thuộc cùng họ, nhưng nó chỉ phủ chỗ chạm
nguồn của tuyến cũ — nó không phủ được "một câu chữ đã hết đúng".

### Verdict

**Hạ tầng: dùng được, và có bằng chứng.** **Chiến lược: chưa có bằng chứng nào** — không
phải bằng chứng xấu, là không có.

Việc đáng làm nhất trước khi cổng mở không phải sửa thêm chỗ nào trên màn hình, mà là trả
lời: *một phiên có kèo trông như thế nào, và làm sao biết hệ xử lý nó đúng?* Ngày đầu tiên
có kèo cũng là ngày đầu tiên toàn bộ nửa dưới của hệ chạy thật.

---

## 5. Kết luận

**Lời từ chối thì tin được. Lời cho phép, khi nó tới, thì chưa đọc được.**

Mọi thứ tạo ra chữ "không được" của hôm nay đều đã đo và đều đứng vững. Không chỗ nào trả lời
"không thấy gì" thành "được". Không chữ ký nào thay được cho phép đo. Đường chặn lệnh chỉ có
một, và nó từ chối ngay lúc tạo đối tượng chứ không phải từng lệnh. Bộ tự kiểm biết kêu. File
xác nhận không mở he hé được gì.

Thứ **chưa** sẵn sàng là **ngày câu trả lời đổi chiều**. Ba phát hiện chỉ cắn vào đúng lúc một
cổng mở ra, hoặc cuốn sổ thôi phẳng:

- Dải trạng thái im lặng về việc đặt lệnh, đúng vào lúc đặt lệnh trở nên khả thi (F5).
- Một lần miễn trừ mở B1 mà **không đâu trên màn hình nói rằng nó được miễn trừ chứ không phải
  được đo** (F3, F4).
- Hai job bảo vệ chạm tới broker trên con đường mà cổng không quản (F2).

**Một cái cổng mà lời từ chối thì chắc chắn, còn lời cho phép thì không đọc được, là cái cổng sẽ
được tin vào đúng ngày không nên tin.**

**Không có gì ở đây bắt buộc phải sửa để tuyến chạy shadow tiếp.** Nhưng trước khi cổng được
phép mở, hai thứ khiến đèn xanh có thể bị đọc sai — F4 và F5 — nên đóng trước. Cả hai là việc ở
giao diện, không đụng gì tới quyết định của bảng đăng ký. F1 rẻ, và nó chữa một phép kiểm hiện
đang không kêu được. F2 thì cần **anh quyết** chứ không cần sửa, và câu hỏi là: **cổng vào lệnh
đóng nghĩa là broker im lặng, hay chỉ nghĩa là tuyến không mở thêm gì mới?**

**Một lưu ý về mức độ phủ.** Lần rà này đi qua: bảng đăng ký, các phép đo của nó, chỗ chặn lệnh,
đường gửi lệnh, điểm vào, file xác nhận, cấu trúc bản ghi đứng sau hai cổng, và đường đi của dữ
liệu từ backend lên màn hình. Nó **không** chạy tuyến, **không** kết nối broker, và **không**
thử được hai cổng đang bị giữ vì chưa có bản ghi.

Trong một kho mà ba lần rà liên tiếp mỗi lần đều ra một lỗi, câu "vùng này đã sạch" là câu bằng
chứng không ủng hộ. Thứ bằng chứng ủng hộ là: **những vùng kể trên đã được đo, và con số nằm
trong từng mục.**
