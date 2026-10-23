# HTTP-LOOPBACK-FQDN-01: proxy policy для `localhost.`

## Что исправлено

Существующие extraction callers (`extractor.py` и
`entity_relation_extractor.py`) классифицируют hostname через
`casefold().rstrip(".")`. Поэтому `http://localhost.:PORT/...` уже является
допустимым локальным endpoint. Shared helper `http_safety.urlopen_no_redirect`
раньше применял только `lower()`: `localhost.` не совпадал с `localhost` и не
получал явный `urllib.request.ProxyHandler({})`.

Стандартный `urllib.request.build_opener` добавляет default `ProxyHandler`, если
его класс не перекрыт переданным handler. При ambient `HTTP_PROXY` и отсутствии
подходящего `NO_PROXY` это оставляло нежелательный proxy route для запроса,
который caller считает локальным. Это условный вывод по исходнику; фактический
proxy/DNS route, передача credentials или пользовательский incident не наблюдались.

Минимальная правка выравнивает **только классификацию** helper:

```python
hostname = (urllib.parse.urlsplit(url).hostname or "").casefold().rstrip(".")
```

Исходный URL (в том числе terminal dot), объект `Request`, method, body и headers
не переписываются. Callers и правила допуска endpoint не изменены. У обычных
`localhost`, IPv4/IPv6 loopback сохраняется explicit empty proxy handler; у
удалённых и localhost-looking имён — прежняя default proxy policy. Это не
глобальное отключение proxies и не DNS/SSRF allowlist.

## Сохранённые границы

- `_NoRedirectHandler` остаётся в исходном opener path; redirect request
  по-прежнему возвращает `None`. Redirect URL и Authorization не пересобираются.
- Подменённый caller'ом `urllib.request.urlopen` по-прежнему вызывается только
  при отличии от сохранённого `_ORIGINAL_URLOPEN`, с тем же объектом запроса.
- `_before_dispatch` вызывается после подготовки route/opener и до отправки;
  timeout ограничивается исходным timeout и возвращённым остатком. Неположительный
  остаток вызывает прежний `TimeoutError`; исключение admission не поглощается.
- Никаких новых SDK, сетевых запросов, SQL, глобальных patches stdlib или изменений
  конфигурации для этого исправления не требуется.

## Регрессия и сила доказательства

Ближайшая shipped регрессия — существующая
`tests/test_http_redirect_safety.py::test_local_http_never_uses_environment_proxy`.
Она расширена чистыми fake-opener проверками `localhost.` как строки и `Request`,
прежних loopback и отрицательных remote/lookalike-host controls. Остальные
функции и assertions файла сохранены.

Отдельный lane-owned bounded SOURCE packet исполняет exact helper source bodies
в fixture namespace с настоящими stdlib `Request`/`ProxyHandler` и synthetic
opener/transport observers, через обычный lifecycle stdlib `unittest` под
неизменным project controller/audit envelope. Старый source используется лишь
как expected old-misroute witness: успешное подтверждение старого нарушения не
означает healthy baseline. Caller parity проверяется STATIC, без исполнения
extractor/model/provider. Итоговые actual exits, roster, SHA и captures находятся
в lane `RESULT.json`, не в этом руководстве.

Наличие или отсутствие handler в переданных аргументах не является наблюдением
настоящего proxy transport. SOURCE proof не квалифицирует native DNS, реальные
redirect responses, actual network/credential egress, live SDK/model startup,
FULL/CI, установленный или загруженный runtime. Server/native tests, публикация,
установка, restart и parent acceptance в этот блок не входят.
