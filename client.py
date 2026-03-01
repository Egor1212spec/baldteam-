import os
import sys
import subprocess
import socket
import threading
import json
import struct
import random
import io

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

import pygame
import tkinter as tk
from tkinter import filedialog

if sys.platform == "win32" and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if load_dotenv:
    load_dotenv(os.path.join(BASE_DIR, ".env"))
MAPS_DIR = os.path.join(BASE_DIR, "maps")
os.makedirs(MAPS_DIR, exist_ok=True)

SERVER_IP = os.getenv('SERVER_IP', '127.0.0.1')
SERVER_PORT = int(os.getenv('SERVER_PORT', 5555))
SERVER_PASSWORD = os.getenv('SERVER_PASSWORD', 'my_super_password')
PLAYER_ROLE = os.getenv('PLAYER_ROLE', 'rtp').lower()

ROLES = ["rtp", "nsh", "br", "dispatcher"]
ROLE_LABELS = {
    "rtp": "РТП", "nsh": "НШ",
    "br": "БР", "dispatcher": "Диспетчер"
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
    "Sandbox Editor [{}] [{}]".format(
        SERVER_IP, ROLE_LABELS.get(PLAYER_ROLE, PLAYER_ROLE)))
clock = pygame.time.Clock()
font = get_ui_font(19)
bigfont = get_ui_font(32)
small_font = get_ui_font(16)
tiny_font = get_ui_font(13)

SWITCH_TO_SANDBOX_EVENT = pygame.USEREVENT + 1

TEXTURE_DIR = os.path.join(BASE_DIR, "textures")
TEXTURES = {}
fire_texture = None

# Fallback цвета для клеток без текстур
CELL_COLORS = {
    "empty":     (12, 22, 45),
    "grass":     (34, 120, 30),
    "trunk":     (90, 55, 20),
    "foliage":   (20, 95, 15),
    "wall":      (130, 120, 100),
    "floor":     (160, 120, 70),
    "wood_floor": (140, 95, 45),
    "stone":     (110, 110, 115),
    "concrete":  (150, 150, 155),
    "water":     (30, 80, 180),
    "hydrant":   (200, 50, 50),
}


def load_textures():
    global TEXTURES, fire_texture
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    TEXTURES = {}

    try:
        fire_texture = pygame.image.load(
            os.path.join(BASE_DIR, "fire.png")).convert_alpha()
    except Exception:
        fire_texture = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
        fire_texture.fill((255, 100, 0, 180))

    for filename in os.listdir(TEXTURE_DIR):
        if not filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            continue
        key = os.path.splitext(filename)[0].lower()
        path = os.path.join(TEXTURE_DIR, filename)
        try:
            img = pygame.image.load(path).convert_alpha()
            if key == "firecar":
                TEXTURES["firecar"] = pygame.transform.scale(img, (64, 128))
            elif key in ("road", "road_straight"):
                TEXTURES["road"] = pygame.transform.scale(
                    img, (CELL * 4, CELL * 4))
            elif key in ("road_right", "road_turn"):
                TEXTURES["road_right"] = pygame.transform.scale(
                    img, (CELL * 5, CELL * 5))
            elif key == "wood":
                # wood.png используется для wall и wood_floor
                TEXTURES["wood"] = pygame.transform.scale(img, (CELL, CELL))
                TEXTURES["wall"] = pygame.transform.scale(img, (CELL, CELL))
                TEXTURES["wood_floor"] = pygame.transform.scale(
                    img, (CELL, CELL))
            else:
                TEXTURES[key] = pygame.transform.scale(img, (CELL, CELL))
        except Exception as e:
            print("Error loading {}: {}".format(filename, e))

    # Если нет текстуры trunk/foliage — создаём цветные заглушки
    if "trunk" not in TEXTURES:
        s = pygame.Surface((CELL, CELL))
        s.fill(CELL_COLORS["trunk"])
        TEXTURES["trunk"] = s
    if "foliage" not in TEXTURES:
        s = pygame.Surface((CELL, CELL))
        s.fill(CELL_COLORS["foliage"])
        TEXTURES["foliage"] = s
    if "grass" not in TEXTURES:
        s = pygame.Surface((CELL, CELL))
        s.fill(CELL_COLORS["grass"])
        TEXTURES["grass"] = s
    if "water" not in TEXTURES:
        s = pygame.Surface((CELL, CELL))
        s.fill(CELL_COLORS["water"])
        TEXTURES["water"] = s
    if "hydrant" not in TEXTURES:
        s = pygame.Surface((CELL, CELL))
        s.fill(CELL_COLORS["hydrant"])
        TEXTURES["hydrant"] = s
    if "stone" not in TEXTURES:
        s = pygame.Surface((CELL, CELL))
        s.fill(CELL_COLORS["stone"])
        TEXTURES["stone"] = s
    if "concrete" not in TEXTURES:
        s = pygame.Surface((CELL, CELL))
        s.fill(CELL_COLORS["concrete"])
        TEXTURES["concrete"] = s
    if "floor" not in TEXTURES:
        s = pygame.Surface((CELL, CELL))
        s.fill(CELL_COLORS["floor"])
        TEXTURES["floor"] = s
    if "wall" not in TEXTURES:
        s = pygame.Surface((CELL, CELL))
        s.fill(CELL_COLORS["wall"])
        TEXTURES["wall"] = s


load_textures()

TOOLS = [
    "grass", "tree", "lake", "house", "wall", "floor", "wood_floor",
    "stone", "concrete", "hydrant", "road", "road_right", "firecar", "ignite"
]
tool_names = {
    "grass": "Трава", "tree": "Дерево", "lake": "Озеро",
    "house": "Дом", "wall": "Стена", "floor": "Пол",
    "wood_floor": "Дер. пол", "stone": "Камень",
    "concrete": "Бетон", "hydrant": "Гидрант",
    "firecar": "АЦ (Машина)", "ignite": "Очаг",
    "road": "Дорога (Прямая)", "road_right": "Дорога (Поворот)"
}
current_tool = "grass"
MULTI_CELL_SIZES = {
    "firecar": (4, 8), "road": (4, 4), "road_right": (5, 5)
}
TOOL_SERVER_NAME = {"road": "road_straight", "road_right": "road_turn"}

# Инструменты заливки всей карты
FILL_TOOLS = {
    "grass": "Залить травой",
    "floor": "Залить полом",
    "stone": "Залить камнем",
    "empty": "Очистить фон",
}

SECTION_KEYS = ["cars", "objects", "floor", "roads", "fill"]
CATEGORIES = {
    "cars": ["firecar"],
    "objects": ["hydrant", "house", "wall", "lake", "tree", "ignite"],
    "floor": ["grass", "floor", "wood_floor", "stone", "concrete"],
    "roads": ["road", "road_right"],
    "fill": [],
}
SECTION_LABELS = {
    "cars": "Машины",
    "objects": "Объекты",
    "floor": "Пол/покрытие",
    "roads": "Дороги",
    "fill": "Залить всё",
}
dropdown_open_section = None
last_dropdown_buttons = []
last_section_buttons = []
last_fill_buttons = []
last_save_rect = None
last_load_rect = None
last_reset_rect = None
last_finish_rect = None


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
    client.connect((SERVER_IP, SERVER_PORT))
    auth_data = {
        'type': 'AUTH',
        'password': SERVER_PASSWORD,
        'role': PLAYER_ROLE
    }
    msg = json.dumps(auth_data).encode('utf-8')
    client.sendall(struct.pack('>I', len(msg)) + msg)
    client.settimeout(5.0)
    raw_msglen = recv_exact(client, 4)
    msglen = struct.unpack('>I', raw_msglen)[0]
    payload = recv_exact(client, msglen)
    auth_reply = json.loads(payload.decode("utf-8"))
    if auth_reply.get("type") != "AUTH_OK":
        raise RuntimeError(
            auth_reply.get("reason", "Auth error"))
    client.settimeout(None)
except Exception as e:
    print("Connection error: {}".format(e))
    pygame.quit()
    sys.exit()


def send_to_server(data):
    try:
        msg = json.dumps(data).encode('utf-8')
        client.sendall(struct.pack('>I', len(msg)) + msg)
    except Exception:
        pass


server_grid = [[[0, 0, "empty"] for _ in range(COLS)] for _ in range(ROWS)]
edit_mode = True
running_sim = False


def receive_thread():
    global server_grid, edit_mode, running_sim
    while True:
        try:
            raw = recv_exact(client, 4)
            if not raw:
                break
            msglen = struct.unpack('>I', raw)[0]
            data = recv_exact(client, msglen)
            if not data:
                break
            state = json.loads(data.decode('utf-8'))
            msg_type = state.get('type', '')

            if msg_type == 'STATE_UPDATE':
                server_grid = state['grid']
                edit_mode = state['edit_mode']
                running_sim = state['running_sim']
            elif msg_type == 'START_GAME':
                print("[CLIENT] START_GAME received")
                pygame.event.post(
                    pygame.event.Event(SWITCH_TO_SANDBOX_EVENT))
                break
        except Exception:
            print("Connection lost")
            break


threading.Thread(target=receive_thread, daemon=True).start()


def save_map():
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON maps", "*.json")],
            initialdir=MAPS_DIR)
        root.destroy()
        if filepath:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(
                    {"cols": COLS, "rows": ROWS, "grid": server_grid},
                    f, ensure_ascii=False)
    except Exception as e:
        print("Save error: {}".format(e))


def load_map():
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON maps", "*.json")],
            initialdir=MAPS_DIR)
        root.destroy()
        if filepath:
            with open(filepath, 'r', encoding='utf-8') as f:
                map_data = json.load(f)
                send_to_server({
                    'type': 'LOAD_MAP',
                    'grid': map_data.get("grid")
                })
    except Exception as e:
        print("Load error: {}".format(e))


def draw_textured_cell(surface, rect, fuel, intensity, ctype, gx, gy):
    x, y = rect.x, rect.y

    # Многоклеточные объекты
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
            pygame.draw.rect(surface, (60, 60, 65),
                             (x, y, CELL * 4, CELL * 4))
        return
    elif ctype == "road_straight_part":
        return

    if ctype == "road_turn_root":
        if "road_right" in TEXTURES:
            surface.blit(TEXTURES["road_right"], (x, y))
        else:
            pygame.draw.rect(surface, (60, 60, 65),
                             (x, y, CELL * 5, CELL * 5))
        return
    elif ctype == "road_turn_part":
        return

    # Огонь
    if intensity > 8:
        scaled = pygame.transform.scale(fire_texture, (CELL, CELL))
        ox = random.randint(-3, 3)
        oy = -random.randint(0, 5) - int(intensity // 10)
        surface.blit(scaled, (x + ox, y + oy))
        return

    # Обычные клетки — ищем текстуру
    texture_key = ctype.replace("_root", "")
    if texture_key.endswith("_part"):
        return

    if texture_key in TEXTURES:
        surface.blit(TEXTURES[texture_key], rect)
    else:
        # Fallback цвет
        color = CELL_COLORS.get(texture_key, (30, 25, 20))
        if texture_key != "empty":
            pygame.draw.rect(surface, color, rect)


def draw_grid():
    for y in range(ROWS):
        for x in range(COLS):
            fuel, intensity, ctype = server_grid[y][x]
            rect = pygame.Rect(x * CELL, y * CELL, CELL, CELL)
            draw_textured_cell(screen, rect, fuel, intensity, ctype, x, y)


def draw_multi_cell_preview():
    if not edit_mode or current_tool not in MULTI_CELL_SIZES:
        return
    mx, my = pygame.mouse.get_pos()
    if mx >= GRID_WIDTH:
        return
    gx = mx // CELL
    gy = my // CELL
    w, h = MULTI_CELL_SIZES[current_tool]
    fits = (0 <= gx <= COLS - w) and (0 <= gy <= ROWS - h)
    pw = w * CELL
    ph = h * CELL
    preview = pygame.Surface((pw, ph), pygame.SRCALPHA)
    if fits:
        preview.fill((100, 255, 100, 45))
        border_color = (80, 255, 80)
        tkey = current_tool
        if tkey in TEXTURES:
            ghost = TEXTURES[tkey].copy()
            ghost.set_alpha(120)
            preview.blit(ghost, (0, 0))
    else:
        preview.fill((255, 80, 80, 50))
        border_color = (255, 60, 60)
    screen.blit(preview, (gx * CELL, gy * CELL))
    pygame.draw.rect(screen, border_color,
                     (gx * CELL, gy * CELL, pw, ph), 2)


def draw_ui():
    global last_dropdown_buttons, last_section_buttons
    global last_fill_buttons
    global last_save_rect, last_load_rect
    global last_reset_rect, last_finish_rect

    last_dropdown_buttons = []
    last_section_buttons = []
    last_fill_buttons = []

    pygame.draw.rect(screen, (25, 25, 35),
                     (GRID_WIDTH, 0, PANEL_WIDTH, HEIGHT))
    pygame.draw.line(screen, (50, 50, 60),
                     (GRID_WIDTH, 0), (GRID_WIDTH, HEIGHT), 3)

    mouse_pos = pygame.mouse.get_pos()
    cur_y = 14

    # Текущий инструмент
    tool_label = tool_names.get(current_tool, current_tool)
    screen.blit(tiny_font.render(
        "Tool: " + tool_label, True, (200, 200, 255)),
        (GRID_WIDTH + 15, cur_y))
    cur_y += 20

    # Секции
    for idx, key in enumerate(SECTION_KEYS):
        rect = pygame.Rect(GRID_WIDTH + 15, cur_y, PANEL_WIDTH - 30, 32)
        last_section_buttons.append({"key": key, "rect": rect})
        active = (dropdown_open_section == key)
        hover = rect.collidepoint(mouse_pos)
        if active:
            color = (70, 100, 170)
        elif hover:
            color = (75, 85, 120)
        else:
            color = (65, 75, 110)
        pygame.draw.rect(screen, color, rect, border_radius=8)

        arrow = "v" if active else ">"
        txt = small_font.render(
            arrow + " " + SECTION_LABELS[key], True, (255, 255, 255))
        screen.blit(txt, (rect.x + 10, rect.y + 7))
        cur_y += 34

        if dropdown_open_section == key:
            cur_y += 4

            if key == "fill":
                # Кнопки заливки
                for fill_tool, fill_label in FILL_TOOLS.items():
                    item_rect = pygame.Rect(
                        GRID_WIDTH + 20, cur_y, PANEL_WIDTH - 40, 28)
                    item_hover = item_rect.collidepoint(mouse_pos)
                    bg = (95, 95, 140) if item_hover else (60, 70, 100)
                    pygame.draw.rect(screen, bg, item_rect,
                                     border_radius=6)
                    last_fill_buttons.append({
                        "rect": item_rect, "tool": fill_tool})
                    screen.blit(small_font.render(
                        fill_label, True, (255, 255, 255)),
                        (item_rect.x + 8, item_rect.y + 5))
                    cur_y += 32
            else:
                for i, item in enumerate(CATEGORIES[key]):
                    item_rect = pygame.Rect(
                        GRID_WIDTH + 20, cur_y,
                        PANEL_WIDTH - 40, 28)
                    is_sel = (current_tool == item)
                    item_hover = item_rect.collidepoint(mouse_pos)
                    if is_sel:
                        bg = (110, 130, 180)
                    elif item_hover:
                        bg = (95, 95, 140)
                    else:
                        bg = (75, 80, 110)
                    pygame.draw.rect(screen, bg, item_rect,
                                     border_radius=6)
                    last_dropdown_buttons.append({
                        "rect": item_rect,
                        "tool": item,
                        "section": key
                    })

                    # Мини-превью цвета/текстуры
                    preview_rect = pygame.Rect(
                        item_rect.x + 4, item_rect.y + 4, 20, 20)
                    if item in TEXTURES:
                        mini = pygame.transform.scale(
                            TEXTURES[item], (20, 20))
                        screen.blit(mini, preview_rect)
                    elif item in CELL_COLORS:
                        pygame.draw.rect(
                            screen, CELL_COLORS[item], preview_rect,
                            border_radius=3)

                    label = tool_names.get(item, item)
                    screen.blit(small_font.render(
                        label, True, (255, 255, 255)),
                        (item_rect.x + 28, item_rect.y + 5))
                    cur_y += 30

            cur_y += 4
        cur_y += 4

    cur_y += 12

    # Кнопки сохранить/загрузить
    half_w = (PANEL_WIDTH - 40) // 2
    last_save_rect = pygame.Rect(GRID_WIDTH + 15, cur_y, half_w, 34)
    last_load_rect = pygame.Rect(
        last_save_rect.right + 10, cur_y, half_w, 34)

    save_hover = last_save_rect.collidepoint(mouse_pos)
    load_hover = last_load_rect.collidepoint(mouse_pos)

    pygame.draw.rect(
        screen,
        (50, 160, 80) if save_hover else (40, 120, 60),
        last_save_rect, border_radius=8)
    st = small_font.render("Сохранить", True, (255, 255, 255))
    screen.blit(st, st.get_rect(center=last_save_rect.center))

    pygame.draw.rect(
        screen,
        (50, 100, 180) if load_hover else (35, 75, 140),
        last_load_rect, border_radius=8)
    lt = small_font.render("Загрузить", True, (255, 255, 255))
    screen.blit(lt, lt.get_rect(center=last_load_rect.center))

    cur_y += 42

    # Кнопка очистить
    last_reset_rect = pygame.Rect(
        GRID_WIDTH + 15, cur_y, PANEL_WIDTH - 30, 36)
    reset_hover = last_reset_rect.collidepoint(mouse_pos)
    pygame.draw.rect(
        screen,
        (255, 70, 70) if reset_hover else (190, 50, 50),
        last_reset_rect, border_radius=9)
    rt = small_font.render("ОЧИСТИТЬ ВСЁ", True, (255, 255, 255))
    screen.blit(rt, rt.get_rect(center=last_reset_rect.center))

    cur_y += 46

    # Кнопка завершить
    last_finish_rect = pygame.Rect(
        GRID_WIDTH + 15, cur_y, PANEL_WIDTH - 30, 40)
    finish_hover = last_finish_rect.collidepoint(mouse_pos)
    pygame.draw.rect(
        screen,
        (255, 180, 30) if finish_hover else (210, 140, 20),
        last_finish_rect, border_radius=9)
    ft = font.render("ЗАВЕРШИТЬ", True, (30, 30, 30))
    screen.blit(ft, ft.get_rect(center=last_finish_rect.center))

    # Статус
    cur_y += 50
    if edit_mode:
        status = "Режим: РЕДАКТОР"
        status_col = (100, 255, 100)
    elif running_sim:
        status = "Режим: СИМУЛЯЦИЯ"
        status_col = (255, 100, 100)
    else:
        status = "Режим: ПАУЗА"
        status_col = (255, 255, 100)
    screen.blit(tiny_font.render(status, True, status_col),
                (GRID_WIDTH + 15, cur_y))


# ================= ГЛАВНЫЙ ЦИКЛ =================
running = True
should_switch = False

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == SWITCH_TO_SANDBOX_EVENT:
            should_switch = True
            running = False
            break

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                send_to_server({'type': 'SPACE'})
            if event.key == pygame.K_r:
                send_to_server({'type': 'R'})

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            if mx < GRID_WIDTH and edit_mode:
                gx = mx // CELL
                gy = my // CELL

                if current_tool in MULTI_CELL_SIZES:
                    w, h = MULTI_CELL_SIZES[current_tool]
                    if (0 <= gx <= COLS - w
                            and 0 <= gy <= ROWS - h):
                        server_tool = TOOL_SERVER_NAME.get(
                            current_tool, current_tool)
                        send_to_server({
                            'type': 'CLICK',
                            'x': gx, 'y': gy,
                            'tool': server_tool
                        })
                else:
                    # Одиночный клик для обычных инструментов
                    if 0 <= gx < COLS and 0 <= gy < ROWS:
                        send_to_server({
                            'type': 'CLICK',
                            'x': gx, 'y': gy,
                            'tool': current_tool
                        })

            elif mx >= GRID_WIDTH:
                # Секции
                for sb in last_section_buttons:
                    if sb['rect'].collidepoint(event.pos):
                        if dropdown_open_section == sb['key']:
                            dropdown_open_section = None
                        else:
                            dropdown_open_section = sb['key']
                        break

                # Инструменты
                for db in last_dropdown_buttons:
                    if db['rect'].collidepoint(event.pos):
                        current_tool = db['tool']
                        break

                # Заливка
                for fb in last_fill_buttons:
                    if fb['rect'].collidepoint(event.pos):
                        send_to_server({
                            'type': 'FILL_BASE',
                            'tool': fb['tool']
                        })
                        break

                if (last_save_rect
                        and last_save_rect.collidepoint(event.pos)):
                    save_map()
                if (last_load_rect
                        and last_load_rect.collidepoint(event.pos)):
                    load_map()
                if (last_reset_rect
                        and last_reset_rect.collidepoint(event.pos)):
                    send_to_server({'type': 'R'})
                if (last_finish_rect
                        and last_finish_rect.collidepoint(event.pos)):
                    send_to_server({
                        'type': 'HOST_READY',
                        'final_grid': server_grid
                    })

    if not running:
        break

    # Зажатая кнопка — рисование кистью
    if edit_mode and pygame.mouse.get_pressed()[0]:
        mx, my = pygame.mouse.get_pos()
        if mx < GRID_WIDTH and current_tool not in MULTI_CELL_SIZES:
            gx = mx // CELL
            gy = my // CELL
            if 0 <= gx < COLS and 0 <= gy < ROWS:
                send_to_server({
                    'type': 'CLICK',
                    'x': gx, 'y': gy,
                    'tool': current_tool
                })

    screen.fill((12, 22, 45))
    draw_grid()
    draw_multi_cell_preview()
    draw_ui()
    pygame.display.flip()
    clock.tick(FPS)

# После выхода из цикла
if should_switch:
    print("=" * 60)
    print("[SWITCH] START_GAME received, launching sandbox...")
    print("=" * 60)

    pygame.quit()
    import time
    time.sleep(0.5)

    if PLAYER_ROLE == "dispatcher":
        script_name = "dp_screen.py"
    else:
        script_name = "game_sandbox.py"

    script_path = os.path.join(BASE_DIR, script_name)

    if not os.path.exists(script_path):
        print("[ERROR] File not found: {}".format(script_path))
        sys.exit(1)

    env = os.environ.copy()
    env["SERVER_IP"] = SERVER_IP
    env["SERVER_PORT"] = str(SERVER_PORT)
    env["SERVER_PASSWORD"] = SERVER_PASSWORD
    env["PLAYER_ROLE"] = PLAYER_ROLE

    try:
        p = subprocess.Popen([sys.executable, script_path], env=env)
        print("[LAUNCH] PID={}".format(p.pid))
    except Exception as e:
        print("[ERROR] Launch failed: {}".format(e))
        import traceback
        traceback.print_exc()

    sys.exit(0)
else:
    client.close()
    pygame.quit()
    sys.exit()