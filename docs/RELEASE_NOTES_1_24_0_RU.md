# Memory Wiki 1.24.0 — заметки к кандидату релиза

> **Не опубликованный релиз.** Это описание предусмотренных изменений и оставшихся проверок, не обещание готовности. Финальный immutable SHA, tag и CI нового релиза не назначены. Никакое состояние профилей или работающих процессов из этих заметок не следует.

## Версия и происхождение

- `plugin.yaml` и `pyproject.toml` исходного кандидата содержат `1.24.0`; Python contract — `>=3.11,<3.15`. Номер metadata не идентифицирует exact source bytes.
- Public `main`, проверенный на срезе 4 октября 2026 года: `438e0b57cb44470c2d47b9210941bea177d379f1`.[5]
- Последний опубликованный GitHub Release на этом срезе — **v1.22.3**. Следующие два — v1.22.2 и v1.22.1, помеченные superseded; v1.24.0 не объявляется опубликованным.[4]
- Исходная локальная композиция: 331 tracked file, composite SHA-256 `d47c2ae30f4b38add05d65253a2c48f4e6cdfa77876a41f6a0c162dbde1ba731`. Это fingerprint непринятого среза, **не Git commit будущего релиза**. Документационный overlay требует новой parent-композиции и freeze.
- Исторический `2bda0efe7f1e5e90c1f0440a89e40f03314f9c21` — session-only база, без нового Codex-маршрута графа. Не использовать его как final PIN; новый полный immutable commit выбирается после приёмки.[2]

## Предусмотренные изменения

Перечень описывает назначение кода исходного кандидата. Он не отмечает ошибки исправленными и не заменяет review/тесты итоговых байтов.

| Область | Предусмотренный контракт | Чего это не доказывает |
|---|---|---|
| Session extraction | Owner-local YAML `settings.extraction`, отдельный provider/model, read-only выбор собственных Codex OAuth grants, без paid fallback. Codex admission `max_tokens` до 9000; OpenRouter и legacy остаются до 3000 | Верность извлечённых фактов, server entitlement, итоговый CI и активацию |
| Graph extraction | Независимый `settings.graph_extraction`, тот же owner-only Codex transport или отдельно выбранный OpenRouter; старый owner-local `MEMORY_WIKI_GRAPH_EXTRACT_MODEL` выше YAML. Auto-graph требует отдельного opt-in | Поддержку графа старым PIN, сохранение отрицания или уже включённую автоматизацию |
| Recall и contradictions | Предусмотрены проверки whole-input social closure, tri-state presence/unknown/absence и ограниченный поиск видимых противоречий | Полноту при SQL `NULL`, прерывание блокирующего SQLite вызова по точному deadline или правильность ответов модели |
| Maintenance/decay | Сохранение нулевых confidence/salience, защита eligible rows, применение полного списка при ограниченном display, закрытие scanner-owned connections | Полную lifecycle/Windows teardown и recovery приёмку |
| Отображение и code graph | Обратимое display encoding, недопущение обрезанного escape; source/revision остаются provenance. Project-bound code readers и source-bound edges | Универсальную semantic prompt-injection защиту, приёмку произвольной прозы или ownerless legacy rows |
| Документы | Явные `document_ingest`/`document_scan`; `MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE=0` отключает automatic turn-start ingestion | Реализованную post-response очередь, таймер или безопасное отключение journal checkpoints |
| Документация | Актуальная provenance, future accepted PIN вместо исторического install PIN, native profile-local команды и раздельные этапы проверки | Публикацию, успешную установку или свежую память в работающем owner |

Native Codex conversion сохраняет requested `gpt-6-luna-900k` до adapter, затем использует wire slug `gpt-6-luna`; это не fallback. Маленькая проба не подтверждает 900K capacity. `max_tokens=9000` для session и 700-token hint графа не являются server-enforced output/spending cap; timeout не гарантирует остановку remote computation или расходования квоты.

## Одобренное ограничение и короткие регрессии

Неполная конструкция «имя + нет» намеренно обрабатывается строго: если после
положительной части появляется только имя и отрицание без явного местоимения,
auxiliary или повторённого действия, извлечение может пропустить факт (fail closed).
Например, `Aster работает на Helix, но Lyra нет.` **не** подтверждает сохраняемую
положительную связь Aster → Helix в этом контракте. Одной заглавной буквы
недостаточно для доказательства смены actor; это осознанная потеря полноты,
а не универсальный разбор языка.

Явные грамматические признаки по-прежнему учитываются: `Aster runs on Helix but
Lyra does not.` (auxiliary) и `Aster runs on Helix but Lyra does not run on Helix
at all.` (полное действие) отделяют отрицание другого actor. Местоимения и
раздельные qualified scopes сохраняются в примере `We use Quartz for production
but we do not use Quartz for development.` Наличие местоимения само по себе
не разрешает противоречие того же actor/object или неизвестный modifier.

Calendar intent — тоже ограниченная лексическая классификация: учитываются
валидность даты, подтверждённая календарная запись и предшествующий контекст
той же clause. `Архив после 2024-03-01, 2/3 часа обработки` остаётся temporal;
`Длина со 3/8, 2 аршина` и `Помнишь смесь с 1.5 г,2 г соли?` — нет. Разделитель
`/` и сокращение `г` сами по себе не доказывают календарь. Это не universal NLP
и не обещание распознать каждую единицу, эллипсис или календарную формулировку.

Переносимые проверки этих границ используют **ASTUNIT**: функции из фактических
repo-relative файлов, без package initialization, SDK-подмен, запросов модели
или persistence. Native/SDK, package/schema/cache, Windows/Linux CI и приёмка
всего релиза остаются отдельными незавершёнными gates. Старый F04 с expected
True и неуспешный исторический gate сохранены; новый отказ — отдельный
owner-approved контракт, не переименование прежнего результата в GREEN.

## Незакрытые ошибки и релизные проверки

На исходном frozen срезе независимые sealed reviews вернули `passed=false`; эти результаты сохранены. В новую локальную композицию включены 20 отдельно принятых overlays и последние три модуля extraction/planner. Их включение и короткие ASTUNIT-регрессии не принимают итоговый plugin: fresh review, package/native gates и exact-source CI остаются pending.

1. **`REVIEW_GRAPH_NEGATION`** — отрицательная evidence могла пройти как положительное directed relation. Нужны реальные positive/negative regressions на новом source.
2. **`REVIEW_SESSION_QUOTE_POLARITY`** — точная, но вырезанная quote могла потерять отрицание исходной фразы и поддержать обратный факт. Проверять source clause, не только literal substring.
3. **`R02-NULL-KEY-FALSE-ABSENCE`** — SQL-valid `NULL` contradiction ID мог привести к false absence. Нужна проверка tri-state при неполном обходе и обычных non-NULL positives.
4. **Полярность recall planner и CI-binding** — отдельная приёмка новых изменений; исторические hash/path-specific tests сохранить и явно классифицировать, не ослаблять утверждения ради зелёного результата.
5. **Итоговая композиция** — независимое ревью и новый полный freeze поверх проверенного main с сохранением unrelated upstream files. Отдельные принятые carriers не принимают весь plugin.
6. **Exact-source CI и artifacts** — применимые Windows/Linux проверки на новом SHA с реальными JUnit/native origins; полное schemas/manifest/cache соответствие, wheel membership/raw bytes, отдельный native ZIP и checkout-excluded installed import/Doctor. Старый CI другого commit не подходит.

Сохранены известные ограничения G04/G05 и raw tilde. Display encoding — структурная граница представления, не семантическая защита от всех атак. Cooperative deadline не прерывает уже заблокированный native вызов. Local FULL/Job/recovery и новый security fix budget этим overlay не предоставляются.

## Установка и активация после приёмки

[Runbook](HERMES-AGENT-DEPLOYMENT.md) и [README](../README.md) дают только условные инструкции. До изменения target нужны trusted host backup с original/untracked/ignored source и recovery/privacy sidecars, проверка ACL/restore, scanner на exact source и отдельное согласие на его caution. Dangerous остаётся блокировкой; missing strict dependency не заменять и strict mode не снижать ради прохождения.

Профили одной установки могут разделять PM dependency environment, но это не разрешение делиться данными или OAuth grants.[3] Metadata-only overlay для duplicate distribution требует собственной проверки native admission/preservation/rollback **до** применения; его установка не подтверждена. Не менять shared lock/facts вручную.

Отчёт rollout должен различать:

1. **Публикацию** — exact remote commit, затем отдельно Release/tag/assets и CI этого SHA.
2. **Установку** — exact deployed payload/metadata по каждому разрешённому профилю, scanner и PM receipt.
3. **Настройки** — только согласованный delta, native writer и readback actual deployed session/graph readers, legacy override отдельно; main/delegation/compression/review модели не заменять.
4. **Свежий CLI** — actual selected PM interpreter, installed origins, Doctor и разрешённая no-storage feature проба; это не cached gateway/Desktop.
5. **Loaded owner** — отдельно разрешённый native reload, новая identity PID/start/source и наблюдаемая feature/prefetch проверка. Self-restart guards не обходить; не запускать stopped сервисы без разрешения.

Owner-local Codex OAuth не разрешает чужую/global grant, refresh/healing/CLI adoption или paid fallback. Backup, источник security dependencies, запросы моделей, рестарт и exact cleanup — отдельные решения. Ни profile cleanup, ни копирование `.env`/`auth.json`/live DB этим релизным документом не разрешены.

## Что не входит в релизные обещания

- Memory Wiki — самостоятельный provider долгосрочной памяти; `memory.provider` сохраняет Wiki. LCM-X — отдельный слой, неподдержанный capture ещё не готов и не задерживает независимый Wiki release.
- Автоматическая доступность Memory Wiki родителю или детям `delegate_task` не заявляется. Пассивный recall дочерних агентов — работа после релиза, не реализованная функция этого overlay.
- Не заявляются универсальная semantic security, server spending cap, качество ответов на реальной истории, уже выполненные backup/restore, установка, сохранение owner settings или активация gateway/Desktop.
- Здесь нет новых тестовых pass counts, финального release SHA, tag или вымышленного CI. Проверки самой документации фиксируются отдельно от функциональной приёмки плагина.

## Sources

[2] https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins
[3] https://hermes-agent.nousresearch.com/docs/reference/package-management
[4] https://github.com/sbrejnev988-coder/hermes-memory-wiki/releases
[5] https://api.github.com/repos/sbrejnev988-coder/hermes-memory-wiki/git/ref/heads/main
