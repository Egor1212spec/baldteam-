"""
game_sandbox.py — Просмотр симуляции пожара.
Все игроки (и хост, и клиенты) попадают сюда после START_GAME.
Подключается к серверу, получает обновления карты и отрисовывает их.
"""

import os
import sys
import json
import socket
import struct
import threading
import random

import pygame

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if load_dotenv is not None:
    load_dotenv(os.path.join(BASE_DIR, ".env"))

# ================= НАСТРОЙКИ =================
SERVER_IP = os.getenv("SERVER_IP", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", "5555"))
SERVER_PASSWORD = os.getenv("SERVER_PASSWORD", "my_super_password")
PLAYER_ROLE = os.getenv("PLAYER_ROLE", "rtp").lower()

CELL = 16
GRID_WIDTH = 960
PANEL_WIDTH = 250
WIDTH = GRID_WIDTH + PANEL_WIDTH
HEIGHT = 704
COLS = GRID_WIDTH // CELL
ROWS = HEIGHT // CELL
FPS = 30

ROLE_LABELS = {
    "rtp": "РТП", "nsh": "НШ", "br": "БР", "dispatcher": "Диспетчер",
    "shtab": "Штаб", "bp1": "БП-1", "bp2": "БП-2",
}


def get_ui_font(size, bold=False):
    font_paths = [
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return pygame.font.Font(path, size)
            except Exception:
                pass
    try:
        return pygame.font.SysFont("arial", size, bold=bold)
    except Exception:
        return pygame.font.Font(None, size)


def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


# ================= PYGAME INIT =================
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption(
    f"Симуляция пожара [{SERVER_IP}] [{ROLE_LABELS.get(PLAYER_ROLE, PLAYER_ROLE)}]"
)
clock = pygame.time.Clock()
font = get_ui_font(19)
big_font = get_ui_font(32, bold=True)
small_font = get_ui_font(16)

# ================= ТЕКСТУРЫ =================
TEXTURE_DIR = os.path.join(BASE_DIR, "textures")
TEXTURES = {}
fire_texture = None


def load_textures():
    global TEXTURES, fire_texture
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    TEXTURES = {}

    fire_path = os.path.join(BASE_DIR, "fire.png")
    try:
        fire_texture = pygame.image.load(fire_path).convert_alpha()
    except Exception:
        fire_texture = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
        fire_texture.fill((255, 100, 0, 180))

    for filename in os.listdir(TEXTURE_DIR):
        if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        key = os.path.splitext(filename)[0].lower()
        path = os.path.join(TEXTURE_DIR, filename)
        try:
            img = pygame.image.load(path).convert_alpha()
            if key in ("firecar",):
                TEXTURES["firecar"] = pygame.transform.scale(img, (64, 128))
            elif key in ("road", "road_straight"):
                TEXTURES["road"] = pygame.transform.scale(img, (CELL * 4, CELL * 4))
            elif key in ("road_right", "road_turn"):
                TEXTURES["road_right"] = pygame.transform.scale(img, (CELL * 5, CELL * 5))
            elif key == "grass":
                TEXTURES["grass"] = pygame.transform.scale(img, (CELL, CELL))
            else:
                TEXTURES[key] = pygame.transform.scale(img, (CELL, CELL))
        except Exception:
            pass

    if "fire" not in TEXTURES and os.path.exists(os.path.join(BASE_DIR, "fire.png")):
        try:
            TEXTURES["fire"] = pygame.image.load(
                os.path.join(BASE_DIR, "fire.png")
            ).convert_alpha()
        except Exception:
            pass


load_textures()

# ================= ЗАГРУЗКА НАЧАЛЬНОЙ КАРТЫ =================
server_grid = [[[0, 0, "empty"] for _ in range(COLS)] for _ in range(ROWS)]

grid_file = os.getenv("GRID_FILE", "")
if grid_file and os.path.exists(grid_file):
    try:
        with open(grid_file, "r", encoding="utf-8") as f:
            server_grid = json.load(f)
        print(f"[SANDBOX] Загружена карта из {grid_file}")
        # Удаляем временный файл
        try:
            os.remove(grid_file)
        except Exception:
            pass
    except Exception as e:
        print(f"[SANDBOX] Ошибка загрузки карты: {e}")

edit_mode = False
running_sim = True

# ================= ПОДКЛЮЧЕНИЕ К СЕРВЕРУ =================
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
connected = False

try:
    print(f"[SANDBOX] Подключение к {SERVER_IP}:{SERVER_PORT}...")
    sock.connect((SERVER_IP, SERVER_PORT))

    auth_data = {"type": "AUTH", "password": SERVER_PASSWORD, "role": PLAYER_ROLE}
    payload = json.dumps(auth_data).encode("utf-8")
    sock.sendall(struct.pack(">I", len(payload)) + payload)

    sock.settimeout(5.0)
    raw_len = recv_exact(sock, 4)
    if raw_len:
        msg_len = struct.unpack(">I", raw_len)[0]
        reply = recv_exact(sock, msg_len)
        if reply:
            auth_reply = json.loads(reply.decode("utf-8"))
            if auth_reply.get("type") == "AUTH_OK":
                connected = True
                print(f"[SANDBOX] Подключено! Роль: {PLAYER_ROLE}")
            else:
                print(f"[SANDBOX] Ошибка авторизации: {auth_reply.get('reason')}")
    sock.settimeout(None)
except Exception as e:
    print(f"[SANDBOX] Ошибка подключения: {e}")


def receive_thread():
    global server_grid, edit_mode, running_sim
    while True:
        try:
            raw = recv_exact(sock, 4)
            if not raw:
                break
            msglen = struct.unpack(">I", raw)[0]
            data = recv_exact(sock, msglen)
            if not data:
                break
            msg = json.loads(data.decode("utf-8"))
            msg_type = msg.get("type", "")

            if msg_type == "STATE_UPDATE":
                server_grid = msg["grid"]
                edit_mode = msg.get("edit_mode", False)
                running_sim = msg.get("running_sim", True)
            elif msg_type == "START_GAME":
                server_grid = msg["grid"]
                edit_mode = False
                running_sim = True
        except Exception:
            print("[SANDBOX] Связь с сервером потеряна")
            break


if connected:
    threading.Thread(target=receive_thread, daemon=True).start()


# ================= ОТРИСОВКА =================
def draw_textured_cell(surface, rect, fuel, intensity, ctype, gx, gy):
    x, y = rect.x, rect.y

    if ctype == "firecar_root":
        if "firecar" in TEXTURES:
            surface.blit(TEXTURES["firecar"], (x, y))
        else:
            pygame.draw.rect(surface, (200, 30, 30), (x, y, 64, 128))
        return
    elif ctype == "firecar_part":
        return

    if ctype == "road_straight_root":
        if "road" in TEXTURES:
            surface.blit(TEXTURES["road"], (x, y))
        else:
            pygame.draw.rect(surface, (60, 60, 65), (x, y, CELL * 4, CELL * 4))
        return
    elif ctype == "road_straight_part":
        return

    if ctype == "road_turn_root":
        if "road_right" in TEXTURES:
            surface.blit(TEXTURES["road_right"], (x, y))
        else:
            pygame.draw.rect(surface, (60, 60, 65), (x, y, CELL * 5, CELL * 5))
        return
    elif ctype == "road_turn_part":
        return

    if intensity > 8:
        scaled = pygame.transform.scale(fire_texture, (CELL, CELL))
        offset_x = random.randint(-3, 3)
        offset_y = -random.randint(0, 5) - intensity // 10
        surface.blit(scaled, (x + offset_x, y + offset_y))
        return

    texture_key = ctype
    if texture_key.endswith("_root"):
        texture_key = texture_key.replace("_root", "")
    if texture_key.endswith("_part"):
        return

    if texture_key in ("road_straight", "road"):
        texture_key = "road"
    elif texture_key in ("road_turn", "road_right"):
        texture_key = "road_right"
    elif texture_key == "floor" and "wood_floor" in TEXTURES:
        texture_key = "wood_floor"
    elif texture_key == "lake" and "water" in TEXTURES:
        texture_key = "water"

    if texture_key in TEXTURES:
        surface.blit(TEXTURES[texture_key], rect)
        return

    color_map = {
        "trunk": (94, 54, 32),
        "foliage": (18, 75, 35),
        "grass": (38, 135, 48),
        "water": (18, 95, 185),
        "lake": (18, 95, 185),
        "stone": (100, 100, 105),
        "concrete": (85, 85, 95),
        "hydrant": (180, 20, 20),
        "road": (60, 60, 65),
        "road_right": (60, 60, 65),
    }

    if texture_key in color_map:
        color = color_map[texture_key]
    elif texture_key in ("wall", "floor", "wood_floor") and fuel > 20:
        color = (158, 112, 52)
    else:
        color = (30, 25, 20)

    pygame.draw.rect(surface, color, rect)


def draw_grid():
    for y in range(ROWS):
        for x in range(COLS):
            fuel, intensity, ctype = server_grid[y][x]
            rect = pygame.Rect(x * CELL, y * CELL, CELL, CELL)
            draw_textured_cell(screen, rect, fuel, intensity, ctype, x, y)


def draw_panel():
    pygame.draw.rect(screen, (25, 25, 35), (GRID_WIDTH, 0, PANEL_WIDTH, HEIGHT))
    pygame.draw.line(screen, (50, 50, 60), (GRID_WIDTH, 0), (GRID_WIDTH, HEIGHT), 3)

    # Заголовок
    title = big_font.render("СИМУЛЯЦИЯ", True, (255, 200, 60))
    screen.blit(title, (GRID_WIDTH + 30, 30))

    # Роль
    role_text = font.render(
        f"Роль: {ROLE_LABELS.get(PLAYER_ROLE, PLAYER_ROLE)}", True, (200, 210, 230)
    )
    screen.blit(role_text, (GRID_WIDTH + 20, 80))

    # Статус
    if running_sim:
        status_color = (100, 255, 100)
        status_text = "Огонь активен"
    else:
        status_color = (255, 200, 80)
        status_text = "Пауза"

    status_surf = font.render(status_text, True, status_color)
    screen.blit(status_surf, (GRID_WIDTH + 20, 120))

    # Подключение
    conn_text = "Подключено" if connected else "Оффлайн"
    conn_color = (100, 255, 100) if connected else (255, 80, 80)
    conn_surf = small_font.render(conn_text, True, conn_color)
    screen.blit(conn_surf, (GRID_WIDTH + 20, 160))

    # Сервер
    srv_surf = small_font.render(f"{SERVER_IP}:{SERVER_PORT}", True, (140, 150, 170))
    screen.blit(srv_surf, (GRID_WIDTH + 20, 185))

    # Статистика карты
    total_cells = 0
    burning = 0
    burned = 0
    for row in server_grid:
        for cell in row:
            fuel, intensity, ctype = cell
            if ctype != "empty":
                total_cells += 1
            if intensity > 8:
                burning += 1
            if fuel <= 0 and ctype not in ("empty", "water", "stone", "concrete",
                                            "road_straight_root", "road_straight_part",
                                            "road_turn_root", "road_turn_part",
                                            "firecar_root", "firecar_part"):
                burned += 1

    y_stat = 240
    screen.blit(small_font.render("─── Статистика ───", True, (150, 160, 180)),
                (GRID_WIDTH + 20, y_stat))
    y_stat += 30
    screen.blit(small_font.render(f"Горит: {burning}", True, (255, 120, 60)),
                (GRID_WIDTH + 20, y_stat))
    y_stat += 25
    screen.blit(small_font.render(f"Сгорело: {burned}", True, (180, 180, 180)),
                (GRID_WIDTH + 20, y_stat))
    y_stat += 25
    screen.blit(small_font.render(f"Объектов: {total_cells}", True, (170, 190, 210)),
                (GRID_WIDTH + 20, y_stat))

    # Подсказка
    hint = small_font.render("ESC — выход", True, (120, 130, 150))
    screen.blit(hint, (GRID_WIDTH + 20, HEIGHT - 40))


# ================= ГЛАВНЫЙ ЦИКЛ =================
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False

    screen.fill((12, 22, 45))
    draw_grid()
    draw_panel()
    pygame.display.flip()
    clock.tick(FPS)

sock.close()
pygame.quit()
sys.exit()