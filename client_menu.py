import os
import sys
import subprocess
import pygame

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if load_dotenv is not None:
    load_dotenv(os.path.join(BASE_DIR, ".env"))

ROLES = ["rtp", "dispatcher", "shtab", "bp1", "bp2"]
ROLE_LABELS = {
    "rtp":        "РТП",
    "dispatcher": "Диспетчер",
    "shtab":      "Штаб",
    "bp1":        "БП-1",
    "bp2":        "БП-2",
}


def get_ui_font(size, bold=False):
    font_paths = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return pygame.font.Font(path, size)
            except Exception:
                pass

    for name in ["arial", "helvetica", "dejavusans", "noto sans", "liberationsans", "segoeui"]:
        matched = pygame.font.match_font(name, bold=bold)
        if matched:
            return pygame.font.Font(matched, size)
    return pygame.font.SysFont(None, size, bold=bold)


def run_menu():
    default_ip = os.getenv("SERVER_IP", "127.0.0.1")
    default_port = os.getenv("SERVER_PORT", "5555")
    default_password = os.getenv("SERVER_PASSWORD", "my_super_password")
    default_role = os.getenv("PLAYER_ROLE", "rtp").lower()

    pygame.init()
    menu_w, menu_h = 760, 800
    screen = pygame.display.set_mode((menu_w, menu_h))
    pygame.display.set_caption("Песочница пожара - Настройки клиента")
    clock = pygame.time.Clock()

    title_font = get_ui_font(36, bold=True)
    font = get_ui_font(24)
    hint_font = get_ui_font(18)

    fields = [
        {"label": "IP сервера",   "value": str(default_ip),      "active": False},
        {"label": "Порт сервера", "value": str(default_port),    "active": False},
        {"label": "Пароль",       "value": str(default_password), "active": False},
    ]

    try:
        role_index = ROLES.index(default_role)
    except ValueError:
        role_index = 0

    dropdown_open = False
    active_field = -1
    error = ""

    while True:
        start_rect = pygame.Rect(130, 700, 220, 56)
        quit_rect  = pygame.Rect(410, 700, 220, 56)

        input_rects = [pygame.Rect(270, 120 + i * 80, 360, 52) for i in range(3)]
        role_rect   = pygame.Rect(270, 340, 360, 52)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return None

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pos = event.pos
                clicked = False

                for i, rect in enumerate(input_rects):
                    if rect.collidepoint(pos):
                        active_field = i
                        dropdown_open = False
                        clicked = True
                        break

                if role_rect.collidepoint(pos):
                    active_field = 3
                    dropdown_open = not dropdown_open
                    clicked = True

                if dropdown_open:
                    item_h = 52
                    for i in range(len(ROLES)):
                        item_rect = pygame.Rect(role_rect.x, role_rect.y + item_h * (i + 1), role_rect.w, item_h)
                        if item_rect.collidepoint(pos):
                            role_index = i
                            dropdown_open = False
                            clicked = True
                            break

                if not clicked:
                    dropdown_open = False
                    active_field = -1

                if start_rect.collidepoint(pos):
                    try:
                        port = int(fields[1]["value"])
                        if not (1 <= port <= 65535):
                            raise ValueError
                        pygame.quit()
                        return {
                            "SERVER_IP": fields[0]["value"],
                            "SERVER_PORT": str(port),
                            "SERVER_PASSWORD": fields[2]["value"],
                            "PLAYER_ROLE": ROLES[role_index],
                        }
                    except ValueError:
                        error = "Порт должен быть числом от 1 до 65535"

                if quit_rect.collidepoint(pos):
                    pygame.quit()
                    return None

            if event.type == pygame.KEYDOWN:
                if active_field == -1:
                    continue

                if active_field < 3:
                    if event.key == pygame.K_BACKSPACE:
                        fields[active_field]["value"] = fields[active_field]["value"][:-1]
                    elif event.key == pygame.K_RETURN:
                        active_field = (active_field + 1) % 3
                    elif event.unicode.isprintable() and len(fields[active_field]["value"]) < 128:
                        fields[active_field]["value"] += event.unicode

                elif active_field == 3:
                    if event.key == pygame.K_UP:
                        role_index = (role_index - 1) % len(ROLES)
                    elif event.key == pygame.K_DOWN:
                        role_index = (role_index + 1) % len(ROLES)
                    elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        dropdown_open = not dropdown_open

        # Отрисовка
        screen.fill((18, 24, 38))
        screen.blit(title_font.render("Меню клиента", True, (240, 244, 255)), (250, 30))
        screen.blit(hint_font.render("Клик по полю → редактирование, роль — клик для списка", True, (170, 188, 220)), (140, 80))

        for i, field in enumerate(fields):
            y = 120 + i * 80
            screen.blit(font.render(field["label"], True, (220, 225, 236)), (95, y + 14))
            color = (95, 160, 255) if i == active_field else (78, 90, 120)
            pygame.draw.rect(screen, color, input_rects[i], width=2, border_radius=8)
            screen.blit(font.render(field["value"], True, (245, 245, 245)), (input_rects[i].x + 14, input_rects[i].y + 12))

        pygame.draw.rect(screen, (78, 90, 120) if active_field != 3 else (95, 160, 255), role_rect, width=2, border_radius=8)
        screen.blit(font.render("Роль", True, (220, 225, 236)), (95, 354))
        screen.blit(font.render(ROLE_LABELS[ROLES[role_index]], True, (245, 245, 245)), (role_rect.x + 14, role_rect.y + 12))
        screen.blit(font.render("▼", True, (180, 190, 220)), (role_rect.right - 45, role_rect.y + 10))

        if dropdown_open:
            item_h = 52
            for i, key in enumerate(ROLES):
                item_y = role_rect.y + item_h * (i + 1)
                item_rect = pygame.Rect(role_rect.x, item_y, role_rect.w, item_h)
                bg_color = (60, 70, 100) if i == role_index else (45, 55, 80)
                pygame.draw.rect(screen, bg_color, item_rect)
                pygame.draw.rect(screen, (95, 160, 255), item_rect, width=1)
                screen.blit(font.render(ROLE_LABELS[key], True, (240, 245, 255)), (item_rect.x + 14, item_rect.y + 12))

        pygame.draw.rect(screen, (40, 160, 80), start_rect, border_radius=8)
        pygame.draw.rect(screen, (170, 60, 60), quit_rect, border_radius=8)
        screen.blit(font.render("Старт",  True, (255, 255, 255)), (208, 715))
        screen.blit(font.render("Выход", True, (255, 255, 255)), (490, 715))

        if error:
            screen.blit(hint_font.render(error, True, (255, 120, 120)), (180, 560))

        pygame.display.flip()
        clock.tick(60)


def main():
    config = run_menu()
    if config is None:
        return

    env = os.environ.copy()
    env.update(config)

    # ← ИЗМЕНЕНИЕ: теперь запускаем waiting_screen.py вместо client.py
    subprocess.Popen(
        [sys.executable, os.path.join(BASE_DIR, "waiting_screen.py")],
        env=env
    )


if __name__ == "__main__":
    main()