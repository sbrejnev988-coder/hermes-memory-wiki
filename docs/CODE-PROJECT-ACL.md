# Изоляция public code graph по active project — отдельный S03-кандидат

## Контракт

Авторитет — существующий `provider.project_scope`, а не `repository_id` модели и не document cross-scope override. Один общий gate использует существующий connection-aware identity mapper. Отсутствующий/пустой канонический active project запрещает чтение; несовпадающий непустой repository запрещён до SELECT содержимого/metadata. Public native JSON возвращает только `{"error": "PermissionError"}`.

Line/neighbors по-прежнему требуют explicit repository. Status с отсутствующим или пустым repository читает только active project: список repositories, files/symbols/chunks/lines/edges, embedded и pending counters. Непустой active project без проиндексированных строк даёт пустой scoped status, не глобальный fallback. Настоящее host-переключение active project на B сохраняет полезные B line-id/file-line/neighbors/status/query.

## Проверено

* Production fix cycle 1 из разрешённых 2; второй не использован.
* Новый RED на исходных S03-байтах: `codeacl-red02`, 120 tests / 57 failures / 0 errors / 0 skips.
* GREEN на тех же тестовых байтах: `codeacl-green01`, 120 passed / 0 failures / 0 errors / 0 skips.
* 86 public/native ACL cases: настоящий Code Shrinker ingress под A и B, in-memory SQLite/FTS и публичный `handle_tool_call` → native JSON. Проверены отсутствие scope, обоесторонняя изоляция, host switch B, default status все counters, ID binding, no-data-SELECT denial, document controls, открытая caller transaction, v1/v2 identity aliases.
* 26 S03 boundary cases скопированы побайтно: обратимый encoding, redacted source, original hashes/citations, limits, transactions, FTS/LIKE и prefetch сохранены.
* 8 существующих standalone module regressions скопированы побайтно: query ACL, prefetch scope и PEM redaction. Это дополнительная совместимость, не подмена native provider proof.
* Изменены только общий gate и четыре read implementation spans; source-boundary/ingress/redactor/recovery/connection helpers не изменены. Baseline initializer/guard/schema/native core и прежние дельты не редактировались.

## Исторические доказательства и oracle

Оригинальный `acl-code-diagnostic` и три его JUnit остаются read-only: baseline 23/8 failures, S03 23/8 failures, minimal 3/1 failure, везде 0 errors. Три parametrized старых leak-characterizations НЕ future GREEN acceptance. Старый ID-binding diagnostic тоже завершался разрешением B под active A: он сохранён исторически; в новом тесте исходный wrong-pair assert сохранён дословно, foreign pair запрещён, host switch B даёт настоящий positive.

Первый собственный RED `codeacl-red01` сохранён (120/58 failures/0 errors). Новый alias oracle первоначально приравнивал represented v1 opaque ID к storage key; существующий S03 представляет этот ID повторно. До production исправлен только новый oracle: все routes сопоставляются с реальным уже scoped query, для migrated v2 сохранена exact-ID проверка. Ни исходные desired specifications, ни исторические positives/boundary assertions не ослаблялись. Исходная display-семантика v1 здесь не менялась.

## Воспроизведение

Из Bash в `C:/Users/Kekl`, существующим interpreter из `coordination.json` (не создавать environment):

```bash
'C:/Users/Kekl/AppData/Local/hermes/installs/cc52de42393663ec/environments/3bc372c3d152454e8f9e117317ccfe0c/venv/Scripts/python.exe' \
  'C:/Users/Kekl/AppData/Local/hermes/artifacts/memory-wiki-parallel-20261003T105356Z/run_non_r03_followup.py' \
  --worker code-project-acl-fix --label NEW_UNIQUE_LABEL --package -- \
  tests/test_public_code_project_acl.py tests/test_continuation_code_boundary.py \
  tests/test_code_graph_scope_acl_regression.py tests/test_code_graph_prefetch_scope.py \
  tests/test_code_graph_pem_redaction.py \
  -o log_file=C:/Users/Kekl/AppData/Local/hermes/artifacts/memory-wiki-parallel-20261003T105356Z/evidence/code-project-acl-fix/NEW_UNIQUE_LABEL/pytest.log
```

Runner deny network/live profiles/foreign writes и использует sparse overlay → frozen full baseline. Запуск под owner-approved isolated native policy 0 не означает strict-mode/gateway acceptance.

## Границы результата

Нового cross-project grant нет. Live storage, настройки профилей, gateway, provider/network calls, install, push/release не затрагивались; full suite не запускался. Широкие lifecycle fixtures и внешняя host-routing/grant authority не сертифицированы этим gate. Sampled resource bounds: lane ≤8 MB, combined ≤512 MB, свободный C не ниже 9,126,805,504 bytes; retained старые артефакты не удалялись. Fresh independent review и merged-source/security/release gates остаются за parent.

Точные raw SHA, union before/after inventory, native origins, JUnit/receipts и public observations: `evidence/code-project-acl-fix/final-report.json`.
