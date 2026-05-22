# Third-Party Licenses

`pst-search` itself is released under the MIT License (see `LICENSE`). It uses
the following third-party components — all under permissive open-source
licenses compatible with redistribution.

## Python dependencies (runtime)

| Package | License | Source |
| --- | --- | --- |
| [FastAPI](https://github.com/fastapi/fastapi) | MIT | <https://github.com/fastapi/fastapi/blob/master/LICENSE> |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause | <https://github.com/encode/uvicorn/blob/master/LICENSE.md> |
| [Starlette](https://github.com/encode/starlette) (via FastAPI) | BSD-3-Clause | <https://github.com/encode/starlette/blob/master/LICENSE.md> |
| [Pydantic](https://github.com/pydantic/pydantic) (via FastAPI) | MIT | <https://github.com/pydantic/pydantic/blob/main/LICENSE> |
| [Jinja2](https://github.com/pallets/jinja) | BSD-3-Clause | <https://github.com/pallets/jinja/blob/main/LICENSE.txt> |
| [Click](https://github.com/pallets/click) | BSD-3-Clause | <https://github.com/pallets/click/blob/main/LICENSE.txt> |
| [Beautiful Soup 4](https://www.crummy.com/software/BeautifulSoup/) | MIT | <https://git.launchpad.net/beautifulsoup/tree/LICENSE> |
| [anyio](https://github.com/agronholm/anyio) (via Starlette) | MIT | <https://github.com/agronholm/anyio/blob/master/LICENSE> |
| [h11](https://github.com/python-hyper/h11) (via Uvicorn) | MIT | <https://github.com/python-hyper/h11/blob/master/LICENSE.txt> |

## Node dependencies (runtime, in `pst_search/node/`)

| Package | License | Source |
| --- | --- | --- |
| [pst-extractor](https://github.com/epfromer/pst-extractor) | MIT | <https://github.com/epfromer/pst-extractor/blob/master/LICENSE> |
| [iconv-lite](https://github.com/ashtuchkin/iconv-lite) (via pst-extractor) | MIT | <https://github.com/ashtuchkin/iconv-lite/blob/master/LICENSE> |
| [long](https://github.com/dcodeIO/long.js) (via pst-extractor) | Apache-2.0 | <https://github.com/dcodeIO/long.js/blob/main/LICENSE> |
| [uuid-parse](https://github.com/zefferus/uuid-parse) (via pst-extractor) | MIT | <https://github.com/zefferus/uuid-parse/blob/master/LICENSE.md> |

`pst-extractor` is itself a TypeScript port of
[java-libpst](https://github.com/rjohnsondev/java-libpst) (MIT), which
independently implements Microsoft's PST format from the publicly-documented
[MS-PST specification](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-pst/).

## Build dependencies (not redistributed in runtime)

| Package | License | Notes |
| --- | --- | --- |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | GPL-2.0-or-later, **with bootloader exception** | The exception explicitly allows applications built with PyInstaller to ship under any license. Source: <https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt>. |
| [Node.js](https://nodejs.org/) (bundled into Windows .exe distribution) | MIT-style mixed (MIT + BSD + ICU + various) | License text is included with the bundled Node runtime in the `.exe` distribution directory. |

## Format specification

This project reads files written in the Microsoft Personal Storage Table
(PST) format. The format is publicly documented by Microsoft under the
[Open Specification Promise](https://learn.microsoft.com/en-us/openspecs/dev_center/ms-devcentlp/051cd324-7081-4f6e-a30c-9c4575c4b921);
no Microsoft code is used or redistributed.

## License compatibility

All runtime dependencies are released under MIT, BSD-3-Clause, or Apache-2.0 —
permissive licenses fully compatible with redistributing `pst-search` under
the MIT License. The notices above satisfy the attribution requirements of
each license; no source-code redistribution obligation exists for any of them.
