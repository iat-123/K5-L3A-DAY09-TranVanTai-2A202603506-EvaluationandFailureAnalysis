# Trace case: từ trace tới quyết định sai đầu tiên

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

## Case: `seeded_regression C-002@11`

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, report `E-seeded_regression-20261117-c8f5` (eval set `c8f59ad2d972`) |
| Triệu chứng | lab8 grader FAIL `status resolved != denied`; `db_fact_kept` = False, `refund_amount_correct` = False (ledger 20.000, nhãn 0, refund_count 1 ≠ 0). Reply "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." — khớp ledger nên `reply_matches_ledger` không bắt: lỗi nằm ở quyết định, không phải ở lời nói. |
| Bước sai đầu tiên | Event **3** `model_override` — `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng hợp đồng (`owner_order_only`, chỉ tool đọc). Event 2 `investigator` đọc DB đúng: đơn O-202 `delivered`, `delay_days = 2` theo DB (không đủ điều kiện hoàn phí ship). Event 3 thay số ngày của DB bằng "5 ngày" trong ticket → event 4 `quote` tính lại thành 20.000 (`SHIP-LATE-03`) → refund được ghi. Mọi bước sau 3 chỉ là hệ quả. |
| Failure mode | **FM-03** ticket_trust (layer model/prompt) |
| Đối chứng | `fixed C-002@11`: event 2 giống hệt; **không có** `model_override`; event 3 `quote {"amount_vnd": 0, "reason": "no_entitlement"}` → reply "chưa đủ điều kiện", ledger 0, PASS. Swarm baseline có cùng lỗi nhưng chỉ ở seed 55 (`seed % 5 == 0`). |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_lab9_trace_case_seeded_regression_c002_fails_at_override` (assert `model_override` đứng ngay sau `investigator`, `DbFactKept` & `RefundAmountCorrect` & `TrialPass` fail) và `test_lab9_trace_case_fixed_c002_passes`. Đã chạy: fail đúng trên `seeded_regression`, pass trên `fixed` (`pytest -m student -k trace_case` → 2 passed). Item E-002 có `provenance.from_trace = "swarm C-002@55 (model_override delay_days)"`. |
| Chưa chắc chắn | Trace chỉ cho thấy agent *dùng* số trong ticket, không cho thấy *vì sao* (MockLLM là luật cứng). Với LLM thật, cần thêm prompt/log của bước parse. Biến thể `quiet_override` tin ticket mà **không** ghi event → `db_fact_kept` mù; khi đó chỉ ledger (`refund_amount_correct`) và slice `denial` bắt được — đã kiểm: gate chặn biến thể này. |

## Quy tắc
- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được.
