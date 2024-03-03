from dataclasses import dataclass, field

from litestar import Request


@dataclass
class Message:
    text: str
    level: int
    tag: str | None = field(default=None, init=False)
    html_class: str | None = field(default=None, init=False)

    DEBUG = 10
    INFO = 20
    SUCCESS = 25
    WARNING = 30
    ERROR = 40

    TAGS = {
        DEBUG: 'alert-secondary',
        INFO: 'alert-info',
        SUCCESS: 'alert-success',
        WARNING: 'alert-warning',
        ERROR: 'alert-danger',
    }

    def __post_init__(self):
        try:
            self.tag = self.TAGS[self.level]
        except KeyError:
            self.html_class = f'tag-{self.level}'

    @staticmethod
    def _message(request: Request, text: str, level: int) -> None:
        if '_messages' not in request.session:
            request.session['_messages']: list[Message] = []
        request.session['_messages'].append(Message(text, level))

    @staticmethod
    def info(request: Request, text: str) -> None:
        Message._message(request, text, Message.INFO)

    @staticmethod
    def success(request: Request, text: str) -> None:
        Message._message(request, text, Message.SUCCESS)

    @staticmethod
    def warning(request: Request, text: str) -> None:
        Message._message(request, text, Message.WARNING)

    @staticmethod
    def error(request: Request, text: str) -> None:
        Message._message(request, text, Message.ERROR)

    @staticmethod
    def messages(request: Request) -> list:
        return request.session.pop('_messages') if '_messages' in request.session else []
