from dataclasses import dataclass, field

from litestar import Request


@dataclass
class Message:
    text: str
    level: int
    html_class: str | None = field(default=None, init=False)
    auto_remove: str | None = field(default=None, init=False)

    DEBUG = 10
    INFO = 20
    SUCCESS = 25
    WARNING = 30
    ERROR = 40

    CLASS = {
        DEBUG: 'border border-secondary bg-secondary-subtle',
        INFO: 'border border-info bg-info-subtle',
        SUCCESS: 'border border-success bg-success-subtle',
        WARNING: 'border border-warning bg-success-warning-subtle',
        ERROR: 'border border-danger bg-danger-subtle',
    }

    AUTO_REMOVE = {
        DEBUG: True,
        INFO: True,
        SUCCESS: True,
        WARNING: False,
        ERROR: False,
    }

    def __post_init__(self):
        self.html_class: str = self.CLASS[self.level]
        self.auto_remove: bool = self.AUTO_REMOVE[self.level]

    @staticmethod
    def _message(request: Request, errors: str | list[str] | Exception, level: int) -> None:
        if '_messages' not in request.session:
            request.session['_messages']: list[Message] = []
        texts: list[str]
        if isinstance(errors, list):
            texts = errors
        elif isinstance(errors, str):
            texts = [errors, ]
        elif isinstance(errors, Exception):
            texts = [str(errors), ]
        else:
            raise ValueError(f'unexpected type [{type(errors)}] for argument [{errors}]')
        for text in texts:
            request.session['_messages'].append(Message(text, level))

    @staticmethod
    def info(request: Request, string_or_list: str | list[str] | Exception) -> None:
        Message._message(request, string_or_list, Message.INFO)

    @staticmethod
    def success(request: Request, string_or_list: str | list[str] | Exception) -> None:
        Message._message(request, string_or_list, Message.SUCCESS)

    @staticmethod
    def warning(request: Request, string_or_list: str | list[str] | Exception) -> None:
        Message._message(request, string_or_list, Message.WARNING)

    @staticmethod
    def error(request: Request, string_or_list: str | list[str] | Exception) -> None:
        Message._message(request, string_or_list, Message.ERROR)

    @staticmethod
    def messages(request: Request) -> list:
        return request.session.pop('_messages') if '_messages' in request.session else []
