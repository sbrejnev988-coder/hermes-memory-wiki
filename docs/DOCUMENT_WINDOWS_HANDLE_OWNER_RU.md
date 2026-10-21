# Windows: ранний владелец file HANDLE

## Исправление

В `_open_windows_allowed_file` единственная продуктовая правка —
`except Exception` → `except BaseException` в уже существующем owning handler.
После успешного `CreateFileW` до передачи в `msvcrt.open_osfhandle` исходный
обработчик пропускал `KeyboardInterrupt`, `SystemExit` и другие прямые
`BaseException`. Теперь здоровый `CloseHandle` выполняется и на этих путях,
а bare `raise` сохраняет исходный объект исключения. Реальные readonly Win32
аргументы, final-path/root/reparse проверки и успешная однонаправленная
HANDLE → CRT FD передача не изменены. Все остальные байты модуля сохранены.

## Самодостаточная регрессия

`tests/test_document_windows_handle_owner.py` — явный Windows component entry.
Collection инертная; обычный вызов test bodies без установленного envelope
отказывает. Baseline witness — точные байты функции из
`e6e721e0b33b1a6f64b2c4751ed7ffd2a9487ed7`, поставляемые в
`tests/fixtures/document_windows_handle_owner_baseline.py.txt`.

Вне ограниченного parent packet регрессия поддерживает явный standalone запуск
на **новом**, исключительно тестовом каталоге:

```text
<selected-python> -I -S -B -u tests/test_document_windows_handle_owner.py --owned-root <new-owned-directory>
```

В текущей lane этот дополнительный запуск **не разрешён**: действуют общий
лимит двух actual target children и двух controller invocations, включая setup
failures. Исполняется только `evidence/invoke.py` → неизменный
`devtools/harness.py::supervise`; никаких скрытых/manual test calls.

До первого product read/import/exec устанавливается deny-by-default audit fence.
Он связывает точные публичные файлы, статически разрешённый import-time closure
выбранной stdlib и её native dependencies. Чтения pycache разрешены только как
точные попытки чтения в собственном пустом prefix, запись bytecode запрещена.
Из native ctypes допускаются только source-bound kernel32 reader/oracle/cleanup
роли и холодный штатный bootstrap ctypes. Сеть, процессы, registry, SQL,
SDK/Core/PM/config/auth/live stores, произвольные libraries/symbols и integer-FD
opens запрещены. Создание dataclass/namedtuple при полном standalone импорте
связано с настоящими stdlib CodeType generators и их exact generated text,
не с общим разрешением `exec('<string>')`.

Восемь literal main IDs перечислены в REQUEST; subtests считаются отдельно.
Три seams — вход в final-path helper, вход в root checker и настоящий
`msvcrt.open_osfhandle` c_call до передачи. Custom BaseException,
KeyboardInterrupt и SystemExit сопоставляются с точным baseline body и
ordinary Exception control. Injector связан с exact owning CodeType; Win32/CRT
API и security/path helpers не заменяются. Подъём из profile отключает profile,
поэтому физическое состояние проверяет отдельный prebound native
`GetFileInformationByHandle` oracle, с file ID/volume/creation identity,
без нового acquire между эффектом и наблюдением.

Baseline leak наблюдается **до** identity-bound fixture emergency cleanup и не
считается product closure. Stale/foreign/unknown номер HANDLE не закрывается.
Healthy FD читается через `os.read`, проверяются readonly write refusal,
физическое закрытие после `os.close`, собственный чужой allowlist root,
missing/directory refusals, повторный healthy и два одновременно возвращённых
CRT владельца.

## Граница доказательства

Это только early-HANDLE Windows component на новых synthetic файлах; не
историческая production attribution, не hostile-code OS sandbox и не
process-tree containment. Supervisor владеет только direct child.
Before-effect `CloseHandle` refusal остаётся UNKNOWN/NOT_INJECTED: вызов close
сам по себе не доказывает release. Полный F04 borrowed-FD/snapshot,
COMMON01/SQLite, SDK/MemoryManager, Linux, FULL, installed/loaded/live pipeline,
publication/install/restart этим packet не квалифицируются. Приёмку и merge
выполняет только parent после отдельного review.
