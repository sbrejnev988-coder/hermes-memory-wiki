# S02-DISPLAY-PREFIX-001: отдельная корректирующая дельта

## Граница и минимальная правка

Изменён только `_context_prefix()` в `continuation/context-prefix-fix/__init__.py`: suffix pattern теперь удаляет также одинокий trailing backslash, а не только `\\u` с 0–3 hex digits. Полный шестисимвольный display escape сохраняется. Для encoder input `\\` полное представление `\\u005c` декодируется в исходный backslash и не отбрасывается.

Контракт относится к уже display-encoded тексту `_context_data()` и code-owned обрамлению: после каждого character-based cut остаётся максимальный целый prefix исходного encoder input. Это **не** обещание полного источника, byte-based/grapheme budget или восстановления ранее redacted/shortened/flattened данных. Admission, guard, секреты, ACL, citations, stored source/hash/evidence, wrappers и бюджеты не менялись. Decoder существует только в тестах; на model-facing path decode не добавлен.

`_context_data()` кодирует перечисленные в S02 ASCII/control delimiters, включая backtick и `#`, но **не tilde**: `~~~` остаётся raw. Это boundary-specific предотвращение перечисленных raw delimiter/control forms, **не** универсальная защита Markdown fences, tokenizer/proxy transformations, семантических инструкций или jailbreaks. S03/R03 и общий trust/security контракт здесь не исправляются и не принимаются.

## Настоящий TDD и native проверки

- Исходный initializer SHA `818af71a7d6608bf3daf2443469944bb33dbd8406d95a28f39ab0ad32725e608` проверен до изменений.
- `cpf-cycle1-red01`: 24 tests, 20 failed, 4 passed, 0 errors/skipped. Один Request fixture использовал длинный `q` token, который существующая upstream redaction заменяла; это отдельная ошибка тестового ожидаемого источника. Gate сохранён, не объявляется полностью чистым behavioral RED.
- До production правки изменён только этот fixture: benign repeated words и явное утверждение, что реальные scrub/redaction не меняют candidate.
- `cpf-cycle1-red02`: тот же native helper/caller subset, 24 tests, 20 failed, 4 passed, 0 errors/skipped; все failures относятся к torn-prefix. Настоящий secondary Request заканчивает candidate на lone backslash в offset 89999 и отказывает в transport, без model response.
- Одна production правка. `cpf-cycle1-green01`: 24 passed, 0 failed/errors/skipped, **тот же test SHA**, что RED02. Source SHA, exact commands, JUnit и native origins находятся в `exact-receipt.json`.
- Итоговый прогон всего **S02-scoped файла**, не полного проекта, содержит исходные 123 controls и новые prefix regressions. Фактические counts, comparison всех прежних testcase names и artifact SHA находятся в `evidence/context-prefix-fix/final-report.json`; результаты не подменяются названием label.

Независимый TEST-only lexer отвергает любой неполный escape, декодирует один раз и отмечает границы source code points. Oracle проверяет decoded-prefix equality и maximal complete prefix, не повторяет production suffix regex. Перебраны все cut offsets corpus strings, включая оригинальные literal escapes/backslashes, соседние escapes, Unicode/astral/surrogate/control characters и raw tilde. Native SQLite/FTS lexical caller отдельно проверяет все шесть границ source/citation escape, полный citation ID, неизменённый source/hash и native turn composition. Все прежние native MemoryManager, canonical/debug pack, suppression/producer, admission, quote/citation/budget controls сохранены.

Portable test resources берутся read-only из настоящего `memory_wiki.__path__` (owned sparse overlay + frozen full package), не копируются в новые production paths и не заменяются SDK/AST/model stubs. Exact resource origins зафиксированы в renderer observations.

## Повторяемый bounded workflow

1. Только standard runner `run_non_r03_followup.py`, `--worker context-prefix-fix --package`, explicit focused tests и новый уникальный label; explicit `-o log_file=<own evidence>/<label>/pytest.log`.
2. `evidence/context-prefix-fix/run_and_seal.py` вызывает runner через точный `coordination.json.sdk_python` с `-I -B -Xutf8`, не импортирует target вне runner. Он пишет actual before/after raw SHA mapping всего frozen 313-file baseline и текущего overlay/effective union, проверяет неизменность native origins и старых S02 source/receipts.
3. В receipt legacy runner fingerprint `48cfe752...` — только stale provenance, **не** current-source seal. Current union fingerprint и individual SHA вычисляются отдельно.
4. Сверять declared JUnit counts с перечисленными testcase elements. Не удалять failed gates/fixtures, не переиспользовать labels. Максимум две production fix cycles; использована одна.
5. После green сохранять exact bytes и передавать свежему независимому reviewer. Этот workflow сохранён в разрешённых docs, а не изменяет профильные skills.

Только owner-approved isolated policy 0, не strict acceptance: synthetic HOME/TEMP, audit-denied network/nested subprocess/live profile/database writes. Нет initialize/shutdown, live DB/model/network, профилей/security/gateway изменений, install/new venv/fullsuite, merge/push или удаления старых артефактов. Лимиты: own lane + evidence ≤ 8,000,000 bytes, global owned ≤ 512,000,000 bytes, C free ≥ 9,126,805,504 bytes; фактические snapshots в receipts. Fresh independent delta review и eventual exact merged composition gate остаются за parent; approval не выдан.
