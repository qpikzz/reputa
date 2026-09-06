# Роли пользователей
ROLE_USER = "user"
ROLE_EMPLOYEE = "employee"
ROLE_MAX_LENGTH = 20

# Лимиты полей
FULL_NAME_MAX_LENGTH = 255
LOGIN_MAX_LENGTH = 255
PHONE_MAX_LENGTH = 20
TELEGRAM_MAX_LENGTH = 255
PASSWORD_HASH_MAX_LENGTH = 255

# Валидация пароля
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 64
PASSWORD_REGEX_UPPERCASE = r"[A-Z]"
PASSWORD_REGEX_LOWERCASE = r"[a-z]"
PASSWORD_REGEX_DIGIT = r"\d"
PASSWORD_REGEX_SPECIAL = r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]"

# Статусы заявки
APPLICATION_STATUS_IN_QUEUE = "in_queue"
APPLICATION_STATUS_AUTO_APPROVED = "auto_approved"
APPLICATION_STATUS_AUTO_REJECTED = "auto_rejected"
APPLICATION_STATUS_EMPLOYEE_APPROVED = "employee_approved"
APPLICATION_STATUS_EMPLOYEE_REJECTED = "employee_rejected"
APPLICATION_STATUS_MAX_LENGTH = 32

# Лимиты полей заявки
AMOUNT_PRECISION = 12
AMOUNT_SCALE = 2

# ID заявки (INFRA-004): первые 10-12 символов sha256-хеша от случайных данных.
# Не автоинкремент и не числовой; длина — в границах допустимого диапазона 10-12.
APPLICATION_ID_LENGTH = 12
PURPOSE_MAX_LENGTH = 1024
TELEGRAM_CHANNEL_MAX_LENGTH = 255

# Оценка скоринга (0–100)
SCORE_MIN = 0
SCORE_MAX = 100

# Пороговая автообработка (APP-003): дефолтные пороги. С APP-008 пороги
# персональные для каждого сотрудника (employee_thresholds), хранятся в БД и
# редактируются в EMP-002; константы ниже — значения по умолчанию.
AUTO_REJECT_THRESHOLD_DEFAULT = 30
AUTO_APPROVE_THRESHOLD_DEFAULT = 70

# Психологический портрет (метрики 0–10)
PORTRAIT_METRIC_MIN = 0
PORTRAIT_METRIC_MAX = 10

# Телефон: количество цифр без учёта ведущего '+'
PHONE_MIN_DIGITS = 7
PHONE_MAX_DIGITS = 15
# Паттерн собирается из лимитов выше, чтобы не дублировать 7/15 в двух местах
PHONE_PATTERN = rf"^\+?\d{{{PHONE_MIN_DIGITS},{PHONE_MAX_DIGITS}}}$"

# Префикс telegram-ника
TELEGRAM_PREFIX = "@"

# Авторизация: имя httpOnly-cookie с JWT
COOKIE_NAME = "access_token"

# Хеширование пароля
PWD_SCHEME_BCRYPT = "bcrypt"

# Код сотрудника для входа (MVP: статичный код, без реальной отправки SMS)
STAFF_LOGIN_CODE = "123456"

# Код восстановления пароля (MVP: статичный код, без реальной отправки SMS)
PASSWORD_RESET_CODE = STAFF_LOGIN_CODE

# Идентификатор сотрудника (AUTH-010): одна англ. буква + 3 цифры + literal
# "room19" (например "A123room19"). Для MVP проверяется только формат — список
# или база допустимых идентификаторов не вводятся (см. AUTH-010.md).
EMPLOYEE_IDENTIFIER_PATTERN = r"^[A-Za-z][0-9]{3}room19$"

# Валидация даты рождения: отсев будущих дат и нереалистичного возраста
USER_MAX_AGE_YEARS = 150

# Заявка: сумма в диапазоне [1 000 ; 10 000 000]
AMOUNT_MIN = 1000
AMOUNT_MAX = 10_000_000

# Файл выписки: лимит размера до парсинга (STMT-001)
STATEMENT_MAX_SIZE_BYTES = 10 * 1024 * 1024

# Банки, выписки которых умеет распознавать STMT-001
STATEMENT_BANK_ALFA = "alfa"
STATEMENT_BANK_SBER = "sber"
STATEMENT_BANK_OZON = "ozon"
STATEMENT_BANK_TBANK = "t-bank"

# Категории операций из структурированной выписки (STMT-001).
# Поступающие операции отделены от трат: расходы агрегируются по категориям,
# поступления — одной суммой, поэтому ключа-«Поступления» в тратах нет.
STMT_CATEGORY_INCOME = "поступления"
STMT_CATEGORY_GROCERIES = "продукты"
STMT_CATEGORY_CAFES = "кафе и рестораны"
STMT_CATEGORY_TRANSPORT = "транспорт"
STMT_CATEGORY_HEALTH = "здоровье"
STMT_CATEGORY_UTILITIES = "жкх и связь"
STMT_CATEGORY_SERVICES = "сервисы и подписки"
STMT_CATEGORY_SHOPPING = "покупки"
STMT_CATEGORY_TRANSFERS = "переводы"
STMT_CATEGORY_OTHER = "прочее"

# JWT: имя httpOnly cookie, в которой хранится токен (единое — COOKIE_NAME выше)

# Сообщения API (общие для роутера, чтобы не дублировать строки)
MSG_USER_ALREADY_EXISTS = "Пользователь с таким логином уже существует"
MSG_STATEMENT_TOO_LARGE = "Файл выписки превышает допустимый размер"
MSG_EMPLOYEE_REQUIRED = "Требуются права сотрудника"
MSG_APPLICATION_NOT_FOUND = "Заявка не найдена"
MSG_APPLICATION_ALREADY_DECIDED = "По заявке уже принято решение"
MSG_STATEMENT_UNPARSABLE = "Не удалось распознать выписку банка. Поддерживаются выписки Альфа-Банка, СберБанка и Озон Банка"
MSG_SCORING_FAILED = "Не удалось рассчитать скоринг заявки"
MSG_NOT_AUTHENTICATED = "Не авторизован"
MSG_INVALID_CREDENTIALS = "Неверный логин или пароль"
MSG_INVALID_STAFF_CODE = "Неверный код"
MSG_NOT_EMPLOYEE = "Вход разрешён только сотрудникам"
MSG_EMPLOYEE_LOGIN_FORBIDDEN = "Сотрудник входит через вход сотрудника"
MSG_PASSWORD_RESET_CODE_SENT = "Если аккаунт найден, код восстановления доступен для ввода"
MSG_INVALID_PASSWORD_RESET_CODE = "Неверный код восстановления"
MSG_ACCOUNT_NOT_FOUND = "Аккаунт не найден"
MSG_PASSWORD_RESET_SUCCESS = "Пароль успешно изменён"
MSG_APPLICATION_NOT_FOUND = "Заявка не найдена"
MSG_THRESHOLD_OUT_OF_RANGE = "Порог должен быть в диапазоне от 0 до 100"
MSG_THRESHOLD_REJECT_BELOW_APPROVE = "Порог авто-отклонения должен быть меньше порога авто-одобрения"
