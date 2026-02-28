import os
import sys
import socket
import threading
import json
import struct
import random
from dotenv import load_dotenv
import pygame
import tkinter as tk
from tkinter import filedialog

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
MAPS_DIR = os.path.join(BASE_DIR, "maps")
os.makedirs(MAPS_DIR, exist_ok=True)

SERVER_IP = os.getenv('SERVER_IP', '127.0.0.1')
SERVER_PORT = int(os.getenv('SERVER_PORT', 5555))
SERVER_PASSWORD = os.getenv('SERVER_PASSWORD', 'my_super_password')
PLAYER_ROLE = os.getenv('PLAYER_ROLE', 'rtp').lower()

ROLES = ["rtp", "nsh", "br", "dispatcher"]
ROLE_LABELS = {
    "rtp": "РТП", "nsh": "НШ", "br": "БР", "dispatcher": "Диспетчер"
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


# ================= НАСТРОЙКИ =================
CELL = 16
GRID_WIDTH = 960
PANEL_WIDTH = 250
WIDTH = GRID_WIDTH + PANEL_WIDTH
HEIGHT = 704
COLS = GRID_WIDTH // CELL
ROWS = HEIGHT // CELL
FPS = 30

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption(
    f"Песочница пожара [{SERVER_IP}] [{ROLE_LABELS.get(PLAYER_ROLE, PLAYER_ROLE)}]"
)
clock = pygame.time.Clock()
font = get_ui_font(19)
bigfont = get_ui_font(32)
small_font = get_ui_font(16)

# ================= ТЕКСТУРЫ =================
TEXTURE_DIR = os.path.join(BASE_DIR, "textures")
TEXTURES = {}


def load_textures():
    global TEXTURES
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    TEXTURES = {}
    print(f"🌲 Загрузка текстур из: {TEXTURE_DIR}")
    for filename in os.listdir(TEXTURE_DIR):
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            key = os.path.splitext(filename)[0].lower()
            try:
                img = pygame.image.load(
                    os.path.join(TEXTURE_DIR, filename)
                ).convert_alpha()
                TEXTURES[key] = pygame.transform.scale(img, (CELL, CELL))
                print(f"   ✓ {filename} → {key}")
            except Exception as e:
                print(f"   ✗ {filename}: {e}")
    print(f"✅ Загружено текстур: {len(TEXTURES)}\n")


load_textures()

try:
    fire_texture = pygame.image.load(
        os.path.join(BASE_DIR, "fire.png")
    ).convert_alpha()
except FileNotFoundError:
    print("❌ fire.png не найден!")
    sys.exit()

# ================= ИНСТРУМЕНТЫ =================
TOOLS = [
    "grass", "tree", "lake", "house", "wall", "floor",
    "wood_floor", "stone", "concrete", "hydrant", "ignite"
]

tool_names = {
    "grass": "Трава", "tree": "Дерево", "lake": "Озеро", "house": "Дом",
    "wall": "Стена", "floor": "Пол", "wood_floor": "Деревянный пол",
    "stone": "Камень", "concrete": "Бетон", "hydrant": "Гидрант", "ignite": "Очаг"
}

current_tool = "grass"

# ================= КОМПОНОВКА ПАНЕЛИ =================
#
#  y=10   «Инструменты»
#  y=32   ┌─────────────────────┐
#         │ 11 кнопок × step=36 │  32 → 32+11×36 = 428
#  y=428  └─────────────────────┘
#  y=434  ── разделитель ────────
#  y=440  «Базовый пол»
#  y=458  ┌─────────────────────┐
#         │ 4 кнопки  × step=32 │  458 → 458+4×32 = 586
#  y=586  └─────────────────────┘
#  y=594  [💾 Сохранить][📂 Загрузить]   h=36  → 630
#  y=638  [🗑  ОЧИСТИТЬ ВСЁ          ]   h=38  → 676
#  y=678  подсказка
#  y=704  ─── низ окна ──────────
#

TOOL_START_Y = 32
TOOL_BTN_H = 34
TOOL_BTN_STEP = 36

SEPARATOR_Y = 434
BASE_LABEL_Y = 440
BASE_START_Y = 458
BASE_BTN_H = 30
BASE_BTN_STEP = 32

HALF_W = (PANEL_WIDTH - 30 - 10) // 2
SAVE_RECT = pygame.Rect(GRID_WIDTH + 15, 594, HALF_W, 36)
LOAD_RECT = pygame.Rect(GRID_WIDTH + 15 + HALF_W + 10, 594, HALF_W, 36)
RESET_RECT = pygame.Rect(GRID_WIDTH + 15, 638, PANEL_WIDTH - 30, 38)

BASE_OPTIONS = [
    {"id": "empty", "name": "Пусто ⬛", "color": (50, 50, 50)},
    {"id": "grass", "name": "Трава 🌿", "color": (38, 135, 48)},
    {"id": "floor", "name": "Дер.Пол 🪵", "color": (158, 112, 52)},
    {"id": "stone", "name": "Камень 🪨", "color": (100, 100, 105)}
]

base_buttons = []
for i, opt in enumerate(BASE_OPTIONS):
    rect = pygame.Rect(
        GRID_WIDTH + 15,
        BASE_START_Y + i * BASE_BTN_STEP,
        PANEL_WIDTH - 30,
        BASE_BTN_H
    )
    base_buttons.append({"rect": rect, "opt": opt})

# ================= СЕТЬ =================
def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    print(f"🔄 Подключение к {SERVER_IP}:{SERVER_PORT}...")
    client.connect((SERVER_IP, SERVER_PORT))
    auth_data = {
        'type': 'AUTH', 'password': SERVER_PASSWORD, 'role': PLAYER_ROLE
    }
    msg = json.dumps(auth_data).encode('utf-8')
    client.sendall(struct.pack('>I', len(msg)) + msg)

    client.settimeout(5.0)
    raw_msglen = recv_exact(client, 4)
    msglen = struct.unpack('>I', raw_msglen)[0]
    payload = recv_exact(client, msglen)
    auth_reply = json.loads(payload.decode("utf-8"))
    if auth_reply.get("type") != "AUTH_OK":
        raise RuntimeError(auth_reply.get("reason", "Ошибка авторизации"))
    client.settimeout(None)
    print(
        f"✅ Авторизация успешна. Роль: "
        f"{ROLE_LABELS.get(PLAYER_ROLE, PLAYER_ROLE)}"
    )
except Exception as e:
    print(f"❌ Ошибка подключения: {e}")
    sys.exit()


def send_to_server(data):
    try:
        msg = json.dumps(data).encode('utf-8')
        client.sendall(struct.pack('>I', len(msg)) + msg)
    except Exception:
        pass


def receive_thread():
    global server_grid, edit_mode, running_sim
    while True:
        try:
            raw = client.recv(4)
            if not raw:
                break
            msglen = struct.unpack('>I', raw)[0]
            data = b''
            while len(data) < msglen:
                data += client.recv(msglen - len(data))
            state = json.loads(data.decode('utf-8'))
            server_grid = state['grid']
            edit_mode = state['edit_mode']
            running_sim = state['running_sim']
        except Exception:
            print("\n❌ Связь потеряна")
            break


server_grid = [[[0, 0, "empty"] for _ in range(COLS)] for _ in range(ROWS)]
edit_mode = True
running_sim = False
threading.Thread(target=receive_thread, daemon=True).start()


# ================= СОХРАНЕНИЕ / ЗАГРУЗКА КАРТЫ =================
def fit_grid(grid, src_rows, src_cols):
    """Подогнать размер сетки под текущие ROWS×COLS"""
    new_grid = [[[0, 0, "empty"] for _ in range(COLS)] for _ in range(ROWS)]
    for y in range(min(src_rows, ROWS)):
        for x in range(min(src_cols, COLS)):
            try:
                new_grid[y][x] = grid[y][x]
            except (IndexError, KeyError):
                pass
    return new_grid


def save_map():
    """Сохранить текущую карту в JSON-файл через диалог"""
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON карты", "*.json"), ("Все файлы", "*.*")],
            initialdir=MAPS_DIR,
            title="Сохранить карту"
        )
        root.destroy()
    except Exception as e:
        print(f"❌ Ошибка диалога: {e}")
        return

    if not filepath:
        return

    try:
        map_data = {
            "version": 1,
            "cols": COLS,
            "rows": ROWS,
            "grid": server_grid
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(map_data, f, ensure_ascii=False)
        print(f"💾 Карта сохранена: {filepath}")
    except Exception as e:
        print(f"❌ Ошибка сохранения: {e}")


def load_map():
    """Загрузить карту из JSON-файла и отправить на сервер"""
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON карты", "*.json"), ("Все файлы", "*.*")],
            initialdir=MAPS_DIR,
            title="Загрузить карту"
        )
        root.destroy()
    except Exception as e:
        print(f"❌ Ошибка диалога: {e}")
        return

    if not filepath:
        return

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            map_data = json.load(f)

        if isinstance(map_data, dict) and "grid" in map_data:
            grid = map_data["grid"]
            file_cols = map_data.get("cols", COLS)
            file_rows = map_data.get("rows", ROWS)
            if file_cols != COLS or file_rows != ROWS:
                print(
                    f"⚠️  Размер карты в файле ({file_cols}×{file_rows}) "
                    f"отличается от текущего ({COLS}×{ROWS}), обрезаю/дополняю"
                )
                grid = fit_grid(grid, file_rows, file_cols)
        elif isinstance(map_data, list):
            grid = map_data
        else:
            print("❌ Неизвестный формат файла")
            return

        send_to_server({'type': 'LOAD_MAP', 'grid': grid})
        print(f"📂 Карта загружена: {filepath}")
    except Exception as e:
        print(f"❌ Ошибка загрузки: {e}")


# ================= ФУНКЦИЯ КНОПОК ИНСТРУМЕНТОВ =================
def get_tool_buttons():
    buttons = []
    y = TOOL_START_Y
    for tool in TOOLS:
        rect = pygame.Rect(GRID_WIDTH + 15, y, PANEL_WIDTH - 30, TOOL_BTN_H)
        buttons.append({"rect": rect, "tool": tool})
        y += TOOL_BTN_STEP
    return buttons


# ================= ОТРИСОВКА ЯЧЕЙКИ =================
def draw_textured_cell(surface, rect, fuel, intensity, ctype, gx, gy):
    x, y = rect.x, rect.y

    if intensity > 0:
        scaled = pygame.transform.scale(fire_texture, (CELL, CELL))
        offset_x = random.randint(-3, 3)
        offset_y = -random.randint(0, 5)
        surface.blit(scaled, (x + offset_x, y + offset_y))
        return

    texture_key = ctype
    if ctype == "floor":
        if "wood_floor" in TEXTURES:
            texture_key = "wood_floor"
        elif "wood" in TEXTURES:
            texture_key = "wood"
    elif ctype in ("water", "lake"):
        if "water" in TEXTURES:
            texture_key = "water"
        elif "lake" in TEXTURES:
            texture_key = "lake"

    if texture_key in TEXTURES:
        surface.blit(TEXTURES[texture_key], rect)
        return

    if ctype == "trunk":
        pygame.draw.rect(surface, (94, 54, 32), rect)
        for i in range(7):
            ox = (gx * 7 + i * 5) % CELL
            oy = (gy * 13 + i * 3) % CELL
            pygame.draw.line(
                surface, (68, 38, 22),
                (x + ox, y + oy), (x + ox + 3, y + oy + 2), 2
            )
    elif ctype == "foliage":
        pygame.draw.rect(surface, (18, 75, 35), rect)
        colors = [(45, 165, 55), (65, 195, 75), (35, 145, 45), (55, 175, 65)]
        seed = (gx * 17 + gy * 23) % 100
        for i in range(14):
            r = 4 if i < 8 else 3
            ox = (seed + i * 11) % (CELL - r * 2) + r
            oy = (seed + i * 19) % (CELL - r * 2) + r
            col = colors[(seed + i) % 4]
            pygame.draw.circle(surface, col, (x + ox, y + oy), r)
    elif ctype == "grass":
        pygame.draw.rect(surface, (38, 135, 48), rect)
        for i in range(6):
            ox = (gx * 3 + i) % (CELL - 3) + 1
            pygame.draw.line(
                surface, (65, 190, 75),
                (x + ox, y + CELL - 2), (x + ox + 1, y + 4), 2
            )
    elif ctype in ("water", "lake"):
        pygame.draw.rect(surface, (18, 95, 185), rect)
        for i in range(5):
            ox = (gy * 7 + i * 5) % CELL
            pygame.draw.line(
                surface, (40, 165, 255),
                (x + ox, y + 4 + i * 3), (x + ox + 8, y + 4 + i * 3), 1
            )
    elif ctype in ("stone", "concrete"):
        color = (85, 85, 95) if ctype == "concrete" else (100, 100, 105)
        pygame.draw.rect(surface, color, rect)
        for i in range(5):
            ox = (gx * 5 + i * 7) % CELL
            oy = (gy * 3 + i * 11) % CELL
            pygame.draw.rect(surface, (60, 60, 70), (x + ox, y + oy, 3, 3))
    elif ctype == "hydrant":
        pygame.draw.rect(surface, (180, 20, 20), rect)
        pygame.draw.circle(
            surface, (255, 220, 60),
            (x + CELL // 2, y + CELL // 2 - 2), CELL // 3
        )
        pygame.draw.rect(
            surface, (255, 255, 255),
            (x + CELL // 2 - 3, y + 4, 6, 8)
        )
    else:
        if fuel > 170:
            color = (92, 52, 32)
        elif fuel > 70:
            color = (158, 112, 52)
        elif fuel > 20:
            color = (42, 148, 52)
        else:
            color = (30, 25, 20)
        pygame.draw.rect(surface, color, rect)


def draw_grid():
    for y in range(ROWS):
        for x in range(COLS):
            fuel, intensity, ctype = server_grid[y][x]
            rect = pygame.Rect(x * CELL, y * CELL, CELL, CELL)
            draw_textured_cell(screen, rect, fuel, intensity, ctype, x, y)


# ================= ОТРИСОВКА UI =================
def draw_ui():
    # Фон панели
    pygame.draw.rect(screen, (25, 25, 35), (GRID_WIDTH, 0, PANEL_WIDTH, HEIGHT))
    pygame.draw.line(
        screen, (50, 50, 60), (GRID_WIDTH, 0), (GRID_WIDTH, HEIGHT), 3
    )

    # Заголовок инструментов
    screen.blit(
        small_font.render("Инструменты", True, (240, 240, 255)),
        (GRID_WIDTH + 20, TOOL_START_Y - 22)
    )

    tool_buttons = get_tool_buttons()
    mouse_pos = pygame.mouse.get_pos()

    for btn in tool_buttons:
        tool = btn["tool"]
        rect = btn["rect"]
        active = (tool == current_tool)
        hover = rect.collidepoint(mouse_pos)

        if active:
            color = (255, 85, 85)
            border = (255, 215, 80)
        elif hover:
            color = (75, 85, 120)
            border = (150, 160, 190)
        else:
            color = (65, 75, 110)
            border = (130, 140, 170)

        pygame.draw.rect(screen, color, rect, border_radius=8)
        pygame.draw.rect(
            screen, border, rect,
            width=3 if active or hover else 1, border_radius=8
        )

        if tool in TEXTURES:
            thumb = pygame.transform.scale(TEXTURES[tool], (24, 24))
            screen.blit(thumb, (rect.x + 7, rect.y + 5))
            tx = rect.x + 38
        else:
            tx = rect.x + 12

        txt = small_font.render(tool_names[tool], True, (255, 255, 255))
        screen.blit(txt, (tx, rect.y + 9))

    # ── Разделитель ──
    pygame.draw.line(
        screen, (60, 70, 95),
        (GRID_WIDTH + 20, SEPARATOR_Y),
        (GRID_WIDTH + PANEL_WIDTH - 20, SEPARATOR_Y), 2
    )

    # ── Базовый пол ──
    screen.blit(
        small_font.render("Базовый пол", True, (240, 240, 255)),
        (GRID_WIDTH + 20, BASE_LABEL_Y)
    )

    for btn in base_buttons:
        rect = btn["rect"]
        opt = btn["opt"]
        hover = rect.collidepoint(mouse_pos)
        col = opt["color"]
        if hover:
            col = (
                min(255, col[0] + 40),
                min(255, col[1] + 40),
                min(255, col[2] + 40)
            )
        pygame.draw.rect(screen, col, rect, border_radius=7)
        pygame.draw.rect(
            screen,
            (200, 200, 200) if hover else (160, 160, 160),
            rect, 2 if hover else 1, border_radius=7
        )
        txt = small_font.render(opt["name"], True, (255, 255, 255))
        screen.blit(txt, txt.get_rect(center=rect.center))

    # ── Сохранить ──
    hover_s = SAVE_RECT.collidepoint(mouse_pos)
    pygame.draw.rect(
        screen,
        (50, 160, 80) if hover_s else (40, 120, 60),
        SAVE_RECT, border_radius=8
    )
    pygame.draw.rect(
        screen,
        (100, 220, 130) if hover_s else (80, 180, 100),
        SAVE_RECT, 2, border_radius=8
    )
    st = small_font.render("Сохранить", True, (255, 255, 255))
    screen.blit(st, st.get_rect(center=SAVE_RECT.center))

    # ── Загрузить ──
    hover_l = LOAD_RECT.collidepoint(mouse_pos)
    pygame.draw.rect(
        screen,
        (50, 100, 180) if hover_l else (35, 75, 140),
        LOAD_RECT, border_radius=8
    )
    pygame.draw.rect(
        screen,
        (80, 150, 230) if hover_l else (60, 120, 200),
        LOAD_RECT, 2, border_radius=8
    )
    lt = small_font.render("Загрузить", True, (255, 255, 255))
    screen.blit(lt, lt.get_rect(center=LOAD_RECT.center))

    # ── Очистить ──
    hover_r = RESET_RECT.collidepoint(mouse_pos)
    pygame.draw.rect(
        screen,
        (255, 70, 70) if hover_r else (190, 50, 50),
        RESET_RECT, border_radius=9
    )
    rt = small_font.render("ОЧИСТИТЬ ВСЁ", True, (255, 255, 255))
    screen.blit(rt, rt.get_rect(center=RESET_RECT.center))

    # ── Подсказка ──
    hint = small_font.render(
        "SPACE — старт/пауза • R — сброс • Ctrl+S/L", True, (170, 180, 200)
    )
    screen.blit(hint, (20, HEIGHT - 26))


# ================= ГЛАВНЫЙ ЦИКЛ =================
running = True
while running:
    tool_buttons = get_tool_buttons()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            mods = pygame.key.get_mods()

            # Ctrl+S / Ctrl+L
            if mods & pygame.KMOD_CTRL:
                if event.key == pygame.K_s:
                    save_map()  # Вызываем напрямую
                elif event.key == pygame.K_l:
                    load_map()  # Вызываем напрямую
            else:
                if event.key == pygame.K_SPACE:
                    send_to_server({'type': 'SPACE'})
                if event.key == pygame.K_r:
                    send_to_server({'type': 'R'})

                key_map = {
                    pygame.K_1: "grass",
                    pygame.K_2: "tree",
                    pygame.K_3: "lake",
                    pygame.K_4: "house",
                    pygame.K_5: "wall",
                    pygame.K_6: "floor",
                    pygame.K_7: "wood_floor",
                    pygame.K_8: "stone",
                    pygame.K_9: "hydrant",
                    pygame.K_c: "concrete",
                    pygame.K_MINUS: "ignite",
                    pygame.K_KP_MINUS: "ignite"
                }
                if event.key in key_map:
                    current_tool = key_map[event.key]

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            clicked_any = False

            # Инструменты
            for btn in tool_buttons:
                if btn["rect"].collidepoint(event.pos):
                    current_tool = btn["tool"]
                    clicked_any = True
                    break

            # Базовый пол
            if not clicked_any:
                for btn in base_buttons:
                    if btn["rect"].collidepoint(event.pos):
                        send_to_server({
                            'type': 'FILL_BASE',
                            'tool': btn["opt"]["id"]
                        })
                        clicked_any = True
                        break

            # Сохранить
            if not clicked_any and SAVE_RECT.collidepoint(event.pos):
                save_map()  # Вызываем напрямую
                clicked_any = True

        # Загрузить
            if not clicked_any and LOAD_RECT.collidepoint(event.pos):
                load_map()  # Вызываем напрямую
                clicked_any = True

            # Очистить
            if not clicked_any and RESET_RECT.collidepoint(event.pos):
                send_to_server({'type': 'R'})
                clicked_any = True

    # Рисование мышью по карте
    if edit_mode and pygame.mouse.get_pressed()[0]:
        mx, my = pygame.mouse.get_pos()
        if mx < GRID_WIDTH:
            gx, gy = mx // CELL, my // CELL
            if 0 <= gx < COLS and 0 <= gy < ROWS:
                send_to_server({
                    'type': 'CLICK', 'x': gx, 'y': gy, 'tool': current_tool
                })

    screen.fill((12, 22, 45))
    draw_grid()
    draw_ui()
    pygame.display.flip()
    clock.tick(FPS)

client.close()
pygame.quit()