# Минимальная filesystem-интеграция: a4 + две принятые FS-дельты

## Что находится в candidate

Задача — один применимый source, а не накопление независимых branches.
Actual common base `a4e118e921f5708ead87d834187805900b08b493`, tree
`c23449a6416a71fd74f2ed26a5d64edf2d6837df`; isolated branch
`integrate/filesystem-portable01`. Изменяются ровно семь Git files:

| Файл | Назначение |
|---|---|
| `document_knowledge_graph.py` | Только три exact accepted raw definitions |
| `tests/test_document_posix_fd_owner.py` | Self-contained eight-main regression, rebound к a4+3defs, case07 extended |
| `tests/fixtures/document_posix_fd_owner_baseline.py.txt` | Unchanged historical f311 two-def baseline |
| `tests/fixtures/document_snapshot_fd_owner_a4_baseline.py.txt` | Exact original a4 one-def snapshot witness |
| `docs/DOCUMENT_POSIX_FD_OWNER_RU.md` | Walker lifetime, fixtures, current binding и Linux scope |
| `docs/DOCUMENT_SNAPSHOT_FD_OWNER_RU.md` | Raw target ownership, early-fault proof и historical/native граница |
| `docs/FILESYSTEM_PORTABLE_INTEGRATION_RU.md` | Состав и воспроизведение |

462 baseline files превращаются в 468: один product file изменён, шесть добавлено.
Все 461 остальных baseline blobs/modes сохраняются; весь product residual вне
трёх definitions, включая Windows implementation/dispatch, guards, parser/jobs
и SQL, byte-identical a4. Git blob/mode и physical byte checks выполняются при
freeze; canonical checkpoint и exact hashes — в `evidence/FREEZE01.json`.

### Входы и их отдельная приёмка

- Snapshot `_snapshot_allowed_file`: exact definition из
  `f31176f2c4233b0f8fa185106351257ded8e1027`, tree
  `1a1794dd91291a5d6d3842d4d6b522b3504dbfc6`. Parent acceptance
  `PARENT_DOCUMENT_SNAPSHOT_FD_OWNER01_ACCEPTANCE.json`, SHA
  `fbcb24f17a6f9280cda281f2622e3df3ca69f8949ce8681ff79eebff2678c7ef`:
  SOURCE-only8, не Windows native и не blanket approval whole f311.
- POSIX `_open_posix_directory` + `_open_posix_allowed_file`: exact definitions из
  `c8edccc0b726ff509f86298a63baf1d81405f4ca`, tree
  `cb07822adbaa187a12897daa7d1680563bb843fa`. Parent acceptance
  `PARENT_DOCUMENT_POSIX_FD_OWNER01_ACCEPTANCE.json`, SHA
  `82dd8760e6c8d8a61425f6f1353976eb7784f234231b2f3604bed64ab43342ab`,
  после independent review `b99fd5540211ea4637fac99dcf2de08b1606867486053729351643c5198fb32e`
  и explicit resource-category disposition. Его original blocked RESULT остаётся
  неизменным; это не retroactive original resource compliance.

Исходные три a4 definitions соответствуют original accepted-patch baselines;
transplant сохраняет exact raw accepted bodies. Не переносится whole module,
`__init__`, document jobs/parser/ spreadsheet policy или unaccepted ancestors.
В a4 нет `spreadsheet_formulas.py` и нет standalone import dependency на него.
Current proof tuple: **document_knowledge_graph / document_extractors / guard**
из самого combined source, не выдуманный spreadsheet module.

## Законченный regression block

Обычное воспроизведение на Linux из candidate root:

```sh
python -B tests/test_document_posix_fd_owner.py
# обычный unittest entry
python -B -m unittest discover -s tests -p test_document_posix_fd_owner.py
```

Stdlib unittest; collection inert, imports full standalone module без package
bootstrap/SDK и без SQL connection. Обе plain fixtures и все helpers/setup/
cleanup/reporting поставляются в candidate. Внешний evidence setup для обычного
entry не нужен. pytest collectability — свойство source, не выполненный FULL.

Ровно **8 mains**; первые шесть сохранили behavioral AST, старый healthy snapshot
body case07 — unchanged suffix. Прежние 28 subtests остаются. Case07 добавляет
8 subcases (candidate/historical × digest/source-constructor × ordinary/fatal),
итого ожидаются 36 subtests. Case08 STATIC rebound проверяет current whole-module
SHA и raw prefix/gaps/suffix вокруг **трёх** definitions, fixture/origin pins и
пустой deny ledger. Raw residual включает Windows, не только prefix/suffix
вокруг двух соседних walkers. Subtests и static checks не дополнительные mains.

Candidate исполняет реальный composed `_snapshot_allowed_file` →
`_open_allowed_file` → текущие оба POSIX walkers, с actual Linux os.open/close/
fstat/symlink/fdopen/flush/fsync. Fault seams локальны к test-owned module
os/hashlib binding; authorization/identity/root/security validators не заменены.
После actual target acquisition и до fixture recovery проверены оба raw FD,
exact ordinary/fatal primary и product cleanup; прежний healthy bytes/hash/
metadata/permissions/source-edit positive сохранён. Historical witness берёт
только exact a4 snapshot body с current real dependencies: это partial
source-extracted body + native OS, **не whole baseline native qualification**.

Новые source/test/dependency bindings изменяют execution contract. Поэтому
исторический whole-eight PASS не переносится; нужен один свежий finished packet
на объединённом target. Старые SOURCE8 и POSIX/Linux8 — отдельные historical
observations, не 16 новых mains и не новое Windows proof.

## Ограниченный actual Linux gate

Для этой новой meaningful integration allocation разрешены максимум две shared
Docker run attempts: первая — целый законченный eight-main packet; вторая —
только coherent justified changed-code/setup affected correction с сохранённой
первой source/capture. Reservation durable **до** `docker run`. Нельзя запускать
неизменённый packet ради receipt или расходовать старые Linux/native бюджеты.

В проекте adapter `evidence/linux_packet.py` — собственная rebound copy прежнего
thin POSIX adapter, использующая unchanged `devtools.harness.supervise`:

```sh
# административные команды внутри owned integration lane; не обычный test setup
python -I -B -X utf8 evidence/linux_packet.py freeze 1
python -I -B -X utf8 evidence/linux_packet.py run 1
```

Exact `docker run` argv хранится в `RUN01.reservation.json`; image **уже cached**
`sha256:1dd3dca85e22886e44fcad1bb7ccab6691dfa83db52214cf9e20696e095f3e36`,
Linux/Python3.11.14. Container `python3 -I -B -u`, nonroot65534:65534;
source bind RO/rootfs RO, network none, capdropALL, nnp, pids32,
memory/memory-swap256000000, CPU1, tmpfs `/work`64M. Все synthetic home/temp paths
в `/work`; ни host homes/socket, ни RW bind, pull/build/install не допускаются.
Прежний audit deny fence устанавливается до product imports; SDK, SQL connect,
network, ctypes и subprocess внутри контейнера запрещены.

Actual interpreter/image/source/test pins фиксируются до test imports. Raw
stdout/stderr, original outer tool result, supervisor `errors`/`primary_error`,
CLI и container exit проверяются отдельно. Exact name/id/image/owner-label
сверяются до удаления **только своего** контейнера; затем inspect id/name должен
подтвердить отсутствие. Printed PASS или reap CLI не заменяют этот readback.

Категории заданы до launches: runtime receipts/raw logs ≤1MB; static source/Git
inventories/patches/preparation и полные authored source files ≤3MB отдельно,
без двойного счёта; review reserve2MB и parent reserve400k. Own15MB, owner7GB,
C-free floor3GB. Ничего исторического не удаляется и не переименовывается ради
cap; current meter не доказывает unsampled peak. Один RESULT ≤64k связывает
scope/outcomes/resources/raw captures/frozen Git; author selfcheck не acceptance.

## Что этот блок не делает

Не меняются old frozen sources, authoritative ACTIVE/todo/acceptance,
currentcommon pointer, installed profiles/Core/SDK/PM, конфигурация/данные/
модели/Vision/indices. Нет merge/push/install/restart или parent acceptance.
Independent finished combined-tree review должен выполнить родитель **до**
любого real common-pointer изменения.

Fresh gate — narrow full-standalone-module **Linux filesystem component**, не
Hermes SDK/MemoryManager/public SQL, не whole-plugin FULL/E2E/CI/release и не
Windows qualification. WindowsF04/native03/COMMON01 остаются BLOCKED/NOT_RUN;
старые native02/cold/B4 и прежний Linux2 budget не пополняются.
