# Judge audit

Chạy: `cd src && python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5` (và `judge_helpful_public.csv`). FAIL là lớp dương (judge có nhiệm vụ *tìm* lỗi).

| Tiêu chí | n | κ | Precision | Recall | Ma trận (tp/fp/fn/tn) | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | 24 / 4 / 6 / 66 | **PASS** | dùng (chỉ cho tone, non-blocking) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | 9 / 0 / 21 / 70 | **FAIL** (κ, R) | loại |

Rogan-Gladen: tone quan sát 0.28 → hiệu chỉnh 0.30; helpful quan sát 0.09 → hiệu chỉnh 0.30 — judge helpful báo thiếu lỗi hơn 3 lần.

## ≥5 case audit thủ công (judge tone, cả 10 bất đồng)
| # | Case | Judge nói | Người nói | Ai đúng? | Sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Thêm luật: xưng "em/anh", hậu tố "nha/nhé" với khách khiếu nại = FAIL. Kèm 2 ví dụ few-shot. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn…" | PASS | FAIL | Người | Xưng hô chuẩn là "anh/chị"; "bạn" = FAIL. |
| 3 | H-029 "…không cần nhắn thêm." | PASS | FAIL | Người | Judge bị đánh lừa bởi "Dạ, vui lòng". Thêm tiêu chí "không ra lệnh/không gạt khách"; yêu cầu judge trích câu vi phạm trước khi chấm. |
| 4 | H-042 "…Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Bỏ yêu cầu "phải xin lỗi": ngắn mà đủ ý, lễ phép là PASS. |
| 5 | H-051 "LogiX đã refund 90.000đ…" | FAIL | PASS | Người | Ghi rõ allowlist từ tiếng Anh CS LogiX cho phép ("refund", "ship"). |
| 6 | H-063 "…và sẽ hoàn thêm cho anh/chị" | PASS | FAIL | Người | Hứa hẹn ngoài kết quả hệ thống không phải lỗi *tone* → chuyển sang grader code (so reply với ledger, FM-08), không bắt judge tone gánh. |
| 7 | H-070 "…ạ 😂😂" | PASS | FAIL | Người | Emoji trong ngữ cảnh khiếu nại = FAIL. |
| 8 | H-081 "…chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Nhãn người sai (đọc nhầm ticket) → sửa nhãn trong CSV gold ở lần gán nhãn tiếp; tính lại κ. |
| 9 | H-088 "Dạ, dạ, LogiX…" | FAIL | PASS | Người (mơ hồ) | Lỗi gõ lặp từ không phải tone; ghi rõ "lỗi chính tả nhẹ không làm FAIL". |
| 10 | H-094 "Da, LogiX da hoan…" (mất dấu) | PASS | FAIL | Người | Mất dấu tiếng Việt / dịch máy = FAIL. |

Mẫu hình: judge tone nhìn từ khoá lịch sự bề mặt ("Dạ", "vui lòng") → bỏ sót lỗi xưng hô/ra lệnh (6/10 là FN). Rubric v2 cần định nghĩa từng loại lỗi + ví dụ âm/dương.

## Kết luận
- **helpful bị loại**: recall 0.30 — trong 30 reply người chấm FAIL, judge chỉ bắt 9; 21 FN gần như toàn bộ là **sai tiền** (HL-015 nói 55.000đ, ledger 40.000đ; HL-043 nói 35.000đ, ledger 20.000đ…) và sai xưng hô ("Ok bạn…"). Judge đọc văn bản, không thấy ledger, nên reply dài, nhiều lời xin lỗi được chấm PASS. Precision 1.0 không cứu được: một gate dựa trên judge này sẽ cho qua ~70% lỗi. Lỗi sai tiền đã có grader code `reply_matches_ledger` (FM-08) — đúng nguyên tắc "tiền luôn chấm bằng code".
- **tone_ok dùng được** nhưng chỉ làm metric theo dõi (non-blocking): κ 0.757 vượt sàn chưa xa, và 6 FN cho thấy rubric cần sửa như bảng trên.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí); cần nhãn người mới, held-out thật, và ít nhất 2 người gán nhãn (H-081 cho thấy nhãn người cũng sai).
