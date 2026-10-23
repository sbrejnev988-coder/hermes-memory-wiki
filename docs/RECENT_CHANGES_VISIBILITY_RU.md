# Видимость recent_changes до LIMIT (RCH01)

## Что изменено

Раньше `_recent_changes` сначала выбирал последние `limit` строк
`memory_changes`, а затем проверял доступ к соответствующим claims. Поэтому
новый недоступный префикс мог целиком вытеснить более старые доступные изменения,
и история ложно оказывалась пустой.

Теперь единственное изменение продуктового кода — в
`MemoryWikiProvider._recent_changes`:

1. Получить настоящий `_claim_visibility_sql(prefix="claims.")`.
2. Выполнить `JOIN claims ON claims.id=memory_changes.claim_id` и применить
   полученный предикат **до** `ORDER BY memory_changes.created_at DESC LIMIT ?`.
   Cutoff, все значения ACL и limit передаются параметрами SQLite.
3. Для каждого выбранного изменения снова прочитать canonical claim, вызвать
   прежний `_claim_visible`, затем прежний `_sanitize_row`.

Новый ACL не вводится. Нет unbounded Python-фильтра или overfetch. Выбирается
только `memory_changes.*`, поэтому поля claims не попадают в публичный результат.
Orphan changes и неизвестная visibility не занимают места в ограниченной выдаче.
Повторная проверка может законно сократить результат при позднем отзыве доступа;
дополнительное заполнение после такого отзыва не добавляется.

Сохранены исходные defaults/clamps (`since_seconds` минимум 1 с прежним fallback
3600, `limit` 1..200 с прежним fallback 50), включительная граница cutoff,
убывающий порядок времени и envelope `{since_seconds, count, changes}`. Поле
`since_seconds` по-прежнему возвращает исходный аргумент. Фильтр claim status не
добавлен: это история изменений, а не только история active claims. Изменения с
одинаковым timestamp сохраняют прежнюю недоопределённость порядка.

## Регрессии и уровень доказательства

`tests/test_recent_changes_visibility_source.py` содержит 15 основных unittest
cases. Это один SOURCE packet, не native/provider/SPI qualification:

- На одной неизменённой настоящей SQLite fixture исходный метод из baseline
  `a4e118e921f5708ead87d834187805900b08b493` наблюдает старое нарушение: семь
  недоступных новых строк при limit 3 скрывают доступный хвост. Кандидат возвращает
  `tail-change`. PASS этого witness означает подтверждение ожидаемого дефекта
  baseline, а не исправность baseline.
- Отдельный candidate control проверяет, что сам ограниченный SELECT содержит
  только доступный хвост, а не большой набор для последующего Python-фильтра.
- Пять scope controls исполняют реальные extracted `_claim_visibility_sql`,
  `_claim_visible`, `_chat_hash` на независимо заданных synthetic principals:
  global, bot, chat, private, project. Для chat проверяется и другой database salt;
  для project — другие bot/session, чужой и пустой project. Ожидания не выводятся
  из проверяемого SQL-предиката.
- Неизвестные/null/пустые scope и orphan не вытесняют доступную строку.
- Проверяются cutoff boundary, newest-visible order, defaults/clamps и ошибки
  преобразования, пустая схема и сохранение history/status semantics.
- После настоящего SELECT/fetchall synthetic adapter выполняет изменение только
  собственной SQLite fixture: canonical revoke и исчезновение claim проверяются
  раздельно. Затем выполняются настоящий hydration и настоящий `_claim_visible`.
- Отдельный sanitizer observer подтверждает вызов только после видимости и
  использование его возвращённой проекции. Настоящий `_sanitize_row` сохранён
  byte-exact, но в этом packet **не исполняется**: это не доказательство native
  redaction или полного реального secret policy.

SQLite — настоящий stdlib `sqlite3`, file-backed, с явным закрытием каждого
fixture-owned connection после case/cleanup. Синтетические данные сохраняются в
собственном scratch; autocommit fixture не представляет production SQL-owner или
transaction authority. Adapter не подделывает rows: каждый SELECT/UPDATE/DELETE
направляется в настоящую собственную SQLite. Clock — synthetic, настоящий `now`
исполняется с этим clock. Не создаётся provider, не импортируются plugin/SDK,
не используется пользовательская память или другие профили.

## Носитель и воспроизводимость

Полный `__init__.py` больше неизменённого лимита binder 1,000,000 bytes. SOURCE
использует минимальный JSON carrier с exact raw spans четырёх исполняемых методов,
`now`, неизменённого sanitizer и исходного baseline метода. Raw SHA, Git blob и
полный originating source связаны внешней metadata-проверкой. Это extraction, не
импорт полного модуля. Carrier не выдаёт дополнительных read/native прав.

Entry загружает весь bound test module через `compile`/`exec`, без bytecode cache
probing, переиспользуя существующий SourceResult/manual-index/correction04
pattern. Перед единственным запуском проверяются полный producer-order roster и
рекурсивные `LOAD_GLOBAL` всех вложенных code objects. Controller — неизменённые
`devtools/harness.py run_source` и `devtools/source_bootstrap.py`; metadata adapter
перепривязывает только собственные output/scratch roots. Оба output guard и
RESULT-relative ancestry проверяются до запуска. Полный candidate Git tree и все
entry/carrier/controller bytes заморожены до packet; после него code не меняется.

Для самостоятельного stdlib запуска без package import задайте новый собственный
`RECENT_CHANGES_TEST_ROOT` и выполните этот test file напрямую с `-I -B -S`.
Он извлечёт текущие methods из соседнего `__init__.py`; exact baseline method
включён в shipped test, поэтому отдельный внешний peer не требуется. Такой запуск
не наследует audit/admission основного SOURCE controller и не входит в текущий
once-only допуск. Без явно заданного root используется собственный уникальный
каталог под TMPDIR. Во время RCH01 применяется только допущенный bound carrier.

## Границы приёмки

`evidence/RESULT.json` и raw captures исходной RCH01 lane (исторический SOURCE input `35a4eec29517a09c1db4898df522f05923e8ea69`) задают фактический исход:
точные case IDs/counts, child exit, stdin/EOF/reap/ownership, audit/ошибки, исходный
outer return, frozen candidate и resource snapshot. Документ сам по себе не
объявляет PASS. Python audit envelope — не OS sandbox.

Для исторического SOURCE input35a4 независимое review и parent acceptance уже завершены; его original15-case packet и границы сохранены. Текущий перенос выполняется поверх принятого guard76031/CI dcd5: тело `_recent_changes`, четыре runtime helper и неисполненный sanitizer span совпадают byte-exact с принятым input, целый regression file не менялся. В полном текущем `__init__.py` изменён только `_recent_changes`; старый baseline literal не перепривязан к current SHA. Нового исполнения SOURCE/SQLite/SDK/native на integration tree не было, а совпадение bodies не доказывает новых взаимодействий. Review/parent acceptance именно составного candidate, FULL, публикация, установка и loaded/live proof остаются отдельными **NOT_RUN/pending** gates. Core/SDK/PM, visibility policy, другие текущие entrypoint bytes, config/auth/env, live DB/Qdrant, профили, Gateway и прежние execution spends сохранены.
