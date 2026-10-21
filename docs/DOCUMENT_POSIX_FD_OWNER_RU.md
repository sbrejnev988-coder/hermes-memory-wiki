# Владение FD при POSIX-обходе документов

## Текущий состав: common a4 + три принятых определения

Основа — `a4e118e921f5708ead87d834187805900b08b493`, tree
`c23449a6416a71fd74f2ed26a5d64edf2d6837df` (462 tracked files).
Поверх неё перенесены **только raw definitions** `_open_posix_directory` и
`_open_posix_allowed_file` из accepted
`c8edccc0b726ff509f86298a63baf1d81405f4ca`, а также `_snapshot_allowed_file`
из accepted `f31176f2c4233b0f8fa185106351257ded8e1027`.

Это не whole-module перенос f311/c8ed: прочие bytes product-модуля и все 461
остальных baseline files/modes остаются a4. В частности, Windows dispatch,
Windows handle implementation, root/path/identity guards, parser/jobs, SQL,
`__init__.py`, `document_extractors.py` и `guard.py` не меняются. В a4 отсутствует
`spreadsheet_formulas.py`; он не требуется его standalone import closure и не
добавляется ради старого proof tuple. Полное описание состава:
[FILESYSTEM_PORTABLE_INTEGRATION_RU.md](FILESYSTEM_PORTABLE_INTEGRATION_RU.md).

## Причина и исправление POSIX walkers

В исходном `_open_posix_allowed_file` обработчик ошибки закрывал первоначальный
`root_fd`, хотя после первого шага владельцем уже был `current_fd`. При
отсутствующем вложенном компоненте descriptor потомка мог остаться открытым;
повторно использованный номер корня мог принадлежать другому файлу. Оба walkers
публиковали новый FD только после `close(previous)`: исключение из close теряло
новый descriptor. `BaseException` не запускал unwind.

Теперь приобретённый child становится текущим владельцем **до** попытки закрыть
предыдущий. Unwind, включая `BaseException`, закрывает текущий descriptor, а не
устаревший номер. Успешный return передаёт один открытый FD caller; caller обязан
его закрыть. Сигнатуры, `O_RDONLY`, `O_DIRECTORY`, `O_NOFOLLOW`, `O_CLOEXEC` и
отказ при отсутствии `O_NOFOLLOW` сохранены. Нового FD framework нет.

## Ошибки закрытия: точная граница

- Fault **после настоящего close** проверяет child unwind и сохранность
  собственного sentinel, занявшего освобождённый номер. Это инъекция локального
  test seam, не утверждение о naturally occurring Linux close failure.
- Fault **до эффекта close** может оставить предыдущий FD открытым. Это genuine
  retained/UNKNOWN, а не подтверждённое освобождение. Нет слепого retry stale
  integer. Состояние сохраняется до identity-checked fixture recovery.
- Прежняя ordinary cleanup semantics сохранена: directory helper может
  замаскировать primary исключением cleanup close; file helper подавляет
  `OSError` cleanup и повторно поднимает primary. Другой cleanup exception может
  заменить primary. Произвольный/постоянный отказ close не объявлен решённым.
- Не заявляется атомарность против асинхронного исключения между отдельными
  Python bytecodes acquisition/assignment/return.

## Самодостаточная регрессия

Из корня candidate на POSIX, stdlib-only:

```sh
python -B tests/test_document_posix_fd_owner.py
# либо обычный unittest без package bootstrap
python -B -m unittest discover -s tests -p test_document_posix_fd_owner.py
```

Collection инертна; полный standalone `document_knowledge_graph` импортируется в
`setUpClass` вместе с **реальными a4 `document_extractors` и `guard`**. Нет SDK,
MemoryManager, package `__init__` или SQL connection. pytest collectable не
означает, что полный pytest был выполнен. Windows пропускает POSIX-класс;
реальный Linux его не пропускает.

Сохраняются восемь main IDs:

1. Настоящие directory/file opens, fstat, bytes, flags, non-inheritable, caller
   transfer и nofollow refusal до acquisition.
2. Missing descendant и reused released-root sentinel; historical POSIX witness.
3. Ordinary/fatal open fault после acquisition обоих walkers, exact primary.
4. After-effect close ordinary/fatal, real close/reuse/fstat/read, child unwind
   и сохранность sentinel; ожидаемые baseline violations отдельно.
5. Before-effect retained previous FD/UNKNOWN без stale retry; прежняя semantics
   cleanup errors обоих helpers.
6. Leaf/intermediate symlinks, outside root и real validation→symlink swap.
7. Полная текущая snapshot composition, новые early digest/source-constructor
   faults ordinary/fatal **после двух настоящих acquisitions**, затем прежний
   healthy bytes/hash/size/mtime/identity/authorize/private-mode/uid и source-edit
   positive без изменения assertions. Подробности —
   [DOCUMENT_SNAPSHOT_FD_OWNER_RU.md](DOCUMENT_SNAPSHOT_FD_OWNER_RU.md).
8. STATIC raw prefix, оба межфункциональных gap (включая Windows), suffix и
   exact three-def pins относительно a4; fixture hashes, реальные origins/hashes
   `document_knowledge_graph`/`document_extractors`/`guard`, пустой audit ledger.

Первые шесть behavioral mains имеют неизменный AST. Прежний healthy case07 body
сохранён целиком; case08 явно rebound к **a4+3defs**, а не к outside-two-def f311.
Прежние 28 subtests сохранены. Case07 добавляет 8 subcases: два fault points ×
ordinary/fatal × candidate/historical snapshot witness. Итого ожидаются 36
subtests, не 36 mains; actual counts определяются primary report.

## Исторические fixtures и роли

`tests/fixtures/document_posix_fd_owner_baseline.py.txt` — неизменные две plain
исходные definitions из f311 (не полный f311 module). Fixture SHA-256
`32bfe93777db165a60c3ae8d641cde1ad9205d849ae1a10d23c851b6ffde6df6`.
Исходный f311 module SHA
`d99921f9adfef892ae1e928f70e6bc308187ce0f1fdc1c9632fa1b7f7de9434d`;
directory lines616–631 SHA
`fd3ad43bdcca571ddd601897de81a8155b491d235412575f7849a0029b487fb2`,
file lines634–652 SHA
`f1c538cadc63d1e25e4ef686b4bd6f711d9a4279a85a7502f0162f847818ba69`.
Эти raw bodies также byte-identical исходным a4 walkers (a4 lines615–630 и
633–651); source pin f311 не переименован в новый current baseline.

Второй plain fixture содержит exact исходный **snapshot body a4**, но его
reader/guards/identity/home dependencies — настоящие текущие a4+3defs.
Это discriminating partial historical witness, не whole-a4 native result.
PASS witness подтверждает ожидаемое старое нарушение; не исправность baseline.

`FDTrace` делегирует настоящим `os.open/close/fstat`; local binding и named fault
constructors не подменяют validator/security/identity. Перед fixture emergency
cleanup сохраняются states всех acquired FD; recovery закрывает только всё ещё
совпадающие `(dev, ino, mode)`, не чужой reused integer. Измеренная production
closure и последующее fixture recovery различаются в observations.

## Допущенный offline Linux packet

`DOCUMENT_POSIX_FD_OFFLINE=1`, CWD `/work`, все synthetic HOME/USERPROFILE/AppData/
HERMES_HOME/TEMP/TMP/TMPDIR под `/work`. Entry устанавливает прежний deny fence
**до full product imports**: subprocess/network/ctypes/SDK и `sqlite3.connect`
запрещены, path writes вне `/work` запрещены. Fence — supervision, не product
sandbox. Дополнительно Docker: source/rootfs RO, network none, nonroot65534,
capdropALL, nnp, pids32, memory256000000, CPU1, tmpfs64M; без host homes/socket/RW
mounts, pull/build/install. Exact команду и readback содержит reservation.

Новый whole-eight packet квалифицирует изменённый combined target и его closure;
это не повтор старой Linux lane, не исправление её immutable RESULT и не перенос
исторических PASS на изменённые тесты. POSIX принят родителем через acceptance
SHA `82dd8760e6c8d8a61425f6f1353976eb7784f234231b2f3604bed64ab43342ab`
после review `b99fd554…` и explicit resource-category disposition; исходный
blocked RESULT остаётся blocked. Fresh outcome берётся только из нового RESULT,
raw captures, actual exits, error ledger и exact container-removal readback.

Ни common pointer, ни merge/push/install, профили, Core/SDK/PM, live data или
WindowsF04/COMMON01 этим блоком не изменяются. Whole-plugin FULL/release/native
MemoryManager/public SQL остаются вне квалификации.
