# Владение raw FD parser snapshot в combined a4+3defs

## Перенесённое исправление

Current base — `a4e118e921f5708ead87d834187805900b08b493`; переносится exact raw
`_snapshot_allowed_file` из accepted
`f31176f2c4233b0f8fa185106351257ded8e1027`, не весь модуль f311.
Дополнительно два принятых POSIX walkers из
`c8edccc0b726ff509f86298a63baf1d81405f4ca`. Остальные bytes модуля и 461 baseline
files/modes — a4. Windows path/handle implementation, dispatch, guards, SQL,
parser/jobs и package bootstrap не меняются. См.
[FILESYSTEM_PORTABLE_INTEGRATION_RU.md](FILESYSTEM_PORTABLE_INTEGRATION_RU.md).

Snapshot сохраняет raw-владельца target от успешного `os.open` через digest
initialization, оба `fdopen`/`__enter__`, copy, flush/fsync и оба `__exit__`.
Target stream заимствует FD через `closefd=False`; единственный raw target
`finally: os.close(snapshot_fd)` действует и при `BaseException`, до ordinary
unlink. Source stream уже заимствовал FD; его закрывает прежний внешний finally.

В исходном a4 target уже приобретён до digest/source constructor/source enter,
но raw target finally отсутствует. Новый real-Linux regression непосредственно
наблюдает это старое нарушение для digest/source constructor на **извлечённом
exact a4 snapshot body**, не для whole historical module. Исходная принятия f311
квалификация была SOURCE-only8; она не становится native Windows задним числом.

## Неизменный контракт и пределы

Сигнатура, identity authorization до чтения, size admission, private paths/modes,
flags, 1 MiB blocks, overflow-before-hash/write, source identity/mtime, SHA-256 и
return metadata сохранены. Native POSIX reader вызывается через настоящий
`_open_allowed_file`, `_lexical_root_for_path` и оба текущих walkers; никакой
разрешающий validator/security stand-in не вводится.

При отказе raw close состояние не объявляется закрытым и stale integer не
повторяется вслепую: UNKNOWN остаётся. Close/unlink exception может маскировать
предыдущий отказ в прежней propagation модели; нового cleanup-error framework
нет. Ordinary errors пытаются unlink snapshot, fatal `BaseException` может
оставить частичный файл/директорию, но finally пытается закрыть оба raw FD.
Удаление директорий не добавлено. Это не доказательство устойчивости к любому
постоянному close failure или между произвольными Python bytecodes.

## Поставляемый self-contained Linux regression

```sh
# из корня candidate на POSIX
python -B tests/test_document_posix_fd_owner.py
# либо
python -B -m unittest discover -s tests -p test_document_posix_fd_owner.py
```

Новый контроль добавлен **в существующий main case07**, а не отдельной suite.
Предыдущие healthy assertions сохранены: exact bytes/hash/size, source identity,
mtime, authorize callback, mode600/dir700/uid, неизменность snapshot после
редактирования исходника. Case07 сначала исполняет восемь новых subcases:

- Current full standalone product × digest/source-constructor × ordinary/fatal.
- Partial historical exact a4 snapshot body × те же четыре faults; ожидаемая
  утечка target служит различающим witness, не healthy baseline PASS.

Named local seams — `early_snapshot_fault`, `digest_constructor`,
`source_constructor`, обёртка test-owned `io.open`. Они изменяют **только** os/
hashlib binding нужного module; `os.open/close/fstat/fdopen`, filesystem, guards,
identity authorization и symlinks настоящие. В момент fault проверены оба
живых FD и их `(dev, ino, mode)`. До fixture emergency cleanup проверяются
source/target closed states и close counts именно от acquisitions, exact primary
exception, факт достижения point и отсутствие изменения source. Candidate
обязан закрыть оба; historical snapshot закрывает source, оставляя target.
Ordinary/fatal unlink behavior наблюдается отдельно. Recovery не засчитывается
как product cleanup.

`tests/fixtures/document_snapshot_fd_owner_a4_baseline.py.txt` содержит **одну
plain исходную snapshot definition** из a4 lines729–791. Fixture compile не
импортирует historical package/module. Её globals явно связаны с реальными
текущими stdlib/typing и unchanged `_file_identity`/`_hermes_home`; reader —
текущий genuine `_open_allowed_file` с принятыми walkers. Поэтому роли честные:
old snapshot body + current actual reader/guards/native Linux OS, не whole-a4
native. Второй POSIX two-def fixture остаётся exact historical f311 с отдельным
pin. Никаких внешних evidence peers для обычного entry не требуется.

## Квалификация: новое и историческое отдельно

Исторический `tests/test_document_snapshot_fd_owner_source.py` из f311 был
SOURCE packet с синтетическим resource ledger: digest/constructors/enters,
target admission, copy/overflow, flush/fsync/exits, close/reused numbers. Этот
файл/whole f311 source не переносится в a4 ради объёма; старый eight-main PASS
остаётся только историческим SOURCE evidence. Не утверждается новый actual
Linux coverage всех его synthetic variants. Fresh Linux case07 проверяет
конкретную composition и ранние digest/source constructor boundaries, а не
весь прежний snapshot SOURCE suite.

Текущий full standalone product импортирует a4 `document_extractors` и `guard`;
`spreadsheet_formulas.py` в a4 отсутствует и не привносится. Actual imported
origins, Python executable/version/SHA, input SHAs, exact image, main/subcase
outcomes, deny ledger, Docker CLI/container/outer exits и cleanup связаны новым
RESULT/captures. До их readback текст документа не объявляет packet PASS.

**NOT_RUN:** Windows native FD/WinDLL, F04/native03/COMMON01, genuine Hermes
SDK/MemoryManager, public tool/SQL owner, FULL/CI/release/installed/loaded.
Старые native02/cold/B4 и Linux attempts не пополняются. SOURCE-only acceptance
f311 не снимает Windows reader/nonowning-FD guard. Новая isolated Linux
component qualification не даёт rollout или common-pointer authority.
