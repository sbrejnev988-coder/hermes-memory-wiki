# Windows: ранний владелец file HANDLE

## Минимальная продуктовая коррекция SRC-01

В `_open_windows_allowed_file` invalid sentinel вычисляется **до** acquire,
а `handle = None` заранее обозначает отсутствие приобретённого владельца.
Owning `try` теперь охватывает сам `CreateFileW`, проверку его результата и
весь прежний путь до передачи в `msvcrt.open_osfhandle`. `except BaseException`
сохранён: здоровый `CloseHandle` вызывается только для уже возвращённого,
не-None и не-invalid HANDLE, затем bare `raise` сохраняет исходное исключение.

Прежняя правка `Exception` → `BaseException` защищала только уже достигнутый
`try`: вычисление sentinel и сравнение результата после acquire оставались
снаружи. Переноса одного sentinel недостаточно, поэтому перенесена и граница
владения. Все байты модуля **вне этого метода** сохранены. Readonly Win32
аргументы, final-path/root/reparse проверки и успешная HANDLE → CRT FD передача
не менялись. C-call с эффектом, но потерянным return, ошибка самого CloseHandle
и физическое состояние после CRT handoff этим исправлением не квалифицированы.

## Исправления native fixture

`tests/test_document_windows_handle_owner.py` сохраняет восемь исходных main IDs,
NativeCall, native binding/fence/entry и прежние healthy/path/identity/readonly/
fatal assertions. Точный e6 body в
`tests/fixtures/document_windows_handle_owner_baseline.py.txt` неизменён.
Candidate SHA и exact inverse self-check обновлены на весь разрешённый function
delta; восстановление e6 body по-прежнему обязано вернуть прежний full-module
SHA, то есть запрещает другие продуктовые изменения.

- Main06 требует настоящего допустимого `winerror`: missing — 2/3, directory —
  5; для продуктового ValueError — точного сообщения соответствующей проверки.
  Audit `PermissionError` без такого native контракта больше не удовлетворяет
  negative oracle. Это **не** разрешение дополнительных ctypes audit events.
- Main08 не индексирует два records после неуспешного/частичного acquire.
  Ранний return возможен при неполной паре, когда acquisition subtest уже
  установил non-success. Его исходная ошибка остаётся в настоящем unittest
  result; finally очищает только возвращённых владельцев. Для двух здоровых
  readers сохранены distinct FD/HANDLE, coexistence и все close assertions.

Collection native fixture инертная; выполнение требует explicit offline
envelope. Shipped standalone entry остаётся документированным, но **в этой
lane не разрешён**:

```text
<selected-python> -I -S -B -u tests/test_document_windows_handle_owner.py --owned-root <new-owned-directory>
```

Две прежние native попытки и их raw failures/refusals сохранены неизменно;
лимит исчерпан (spent 2, remaining 0). Они остановились на fence без наблюдаемого
приобретённого HANDLE. Поэтому прежний baseline leak нельзя называть физически
наблюдённым, а исправленный fixture — проверенным Windows component.

## Shipped NON-NATIVE SOURCE regression

`tests/test_document_windows_lifetime_source.py` исполняется только через
неизменный canonical `devtools/harness.py run ... --scope source --timeout 60`.
Входы — два малых exact function carriers
`tests/fixtures/document_windows_lifetime_{candidate,b0cd}.py.txt`, неизменный e6
fixture и native test source. Полный продукт и native entry не импортируются.
Metadata preflight связывает каждый carrier с точным raw span полного Git blob;
это проверка соответствия исходников, не native dependency authority.

Шесть literal mains отдельно проверяют:

1. SHA/exact inverse binding и статическую границу owner `try`.
2. Здоровый readonly/handoff и sentinel failures **до** acquire; exact b0cd
   witness ожидаемо оставляет только synthetic logical lease.
3. Ordinary/fatal primary identity и logical cleanup после acquire: compare,
   info constructor, get-info, final-path, root и handoff entry; отдельный b0cd
   compare witness демонстрирует старое окно.
4. Before-effect acquire errors, invalid HANDLE, info/attributes/root refusals;
   invalid/unacquired значение не закрывается.
5. Source-extracted main06 под настоящим unittest reporter: допустимые synthetic
   native/product negatives принимаются; audit, чужой ValueError и неверный
   winerror дают non-success.
6. Source-extracted main08 под настоящим unittest reporter: оба/первый/второй
   acquire errors сохраняются, новый IndexError не появляется; здоровая пара
   остаётся одновременно живой до исходных close assertions.

Все ctypes/kernel/msvcrt, final-path/root, receiver и OS operations здесь
**явно synthetic**. Dependency namespaces локальны для извлечённой функции;
нет actual ctypes/_ctypes/msvcrt import, глобального sys.modules/Core patch,
реальных HANDLE/FD, SQL/SDK/network/model/live вызовов. Один разрешённый
SOURCE controller/child, включая setup errors; не больше 64 synthetic variants,
никаких rehearsal/manual вызовов тестов и повторов после отказа. Фактические
counts/exits/captures и оригинальный outer return хранятся в lane RESULT со
ссылкой на canonical harness RESULT; Git bytes заморожены до packet.

## Граница доказательства

SOURCE PASS доказывает только соответствие exact bodies и synthetic lifetime/
oracle control flow. Он **не доказывает физическое закрытие HANDLE**, CRT FD
transfer, native path/ACL/identity, SDK authority или full-module startup.
Native/Windows component/F04 snapshot/SQLite/Linux/FULL/installed/loaded/live
остаются UNKNOWN/NOT_RUN. Это не OS sandbox и не process-tree containment.
Нового native допуска, acceptance/merge/publication/install/restart нет;
независимое feature review e6→candidate и приёмку выполняет parent.
