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

# ================= НАСТРОЙКИ ПРИЛОЖЕНИЯ =================
if sys.platform == "win32" and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if load_dotenv:
    load_dotenv(os.path.join(BASE_DIR, ".env"))
MAPS_DIR = os.path.join(BASE_DIR, "maps")
os.makedirs(MAPS_DIR, exist_ok=True)

# ================= СЕТЕВЫЕ НАСТРОЙКИ КЛИЕНТА =================
SERVER_IP = os.getenv('SERVER_IP', '127.0.0.1')
SERVER_PORT = int(os.getenv('SERVER_PORT', 5555))
SERVER_PASSWORD = os.getenv('SERVER_PASSWORD', 'my_super_password')
PLAYER_ROLE = os.getenv('PLAYER_ROLE', 'rtp').lower()

ROLES = ["rtp", "nsh", "br", "dispatcher"]
ROLE_LABELS = {"rtp": "РТП", "nsh": "НШ", "br": "БР", "dispatcher": "Диспетчер"}

def get_ui_font(size, bold=False):
    font_paths = [
        "C:/Windows/Fonts/arial.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try: return pygame.font.Font(path, size)
            except Exception: pass
    try: return pygame.font.SysFont("arial", size, bold=bold)
    except Exception: return pygame.font.Font(None, size)

# ================= НАСТРОЙКИ PYGAME =================
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
pygame.display.set_caption(f"Песочница пожара [{SERVER_IP}] [{ROLE_LABELS.get(PLAYER_ROLE, PLAYER_ROLE)}]")
clock = pygame.time.Clock()
font = get_ui_font(19)
bigfont = get_ui_font(32)
small_font = get_ui_font(16)

# === [ИЗМЕНЕНИЕ 1] Создаем кастомное событие для переключения ===
SWITCH_TO_SANDBOX_EVENT = pygame.USEREVENT + 1

# ================= ТЕКСТУРЫ =================
TEXTURE_DIR = os.path.join(BASE_DIR, "textures")
TEXTURES = {}
fire_texture = None

def load_textures():
    global TEXTURES, fire_texture
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    TEXTURES = {}
    try: fire_texture = pygame.image.load(os.path.join(BASE_DIR, "fire.png")).convert_alpha()
    except Exception:
        fire_texture = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
        fire_texture.fill((255, 100, 0, 180))

    for filename in os.listdir(TEXTURE_DIR):
        if not filename.lower().endswith(('.png', '.jpg', '.jpeg')): continue
        key = os.path.splitext(filename)[0].lower()
        path = os.path.join(TEXTURE_DIR, filename)
        try:
            img = pygame.image.load(path).convert_alpha()
            if key in ("firecar",): TEXTURES["firecar"] = pygame.transform.scale(img, (64, 128))
            elif key in ("road", "road_straight"): TEXTURES["road"] = pygame.transform.scale(img, (CELL * 4, CELL * 4))
            elif key in ("road_right", "road_turn"): TEXTURES["road_right"] = pygame.transform.scale(img, (CELL * 5, CELL * 5))
            else: TEXTURES[key] = pygame.transform.scale(img, (CELL, CELL))
        except Exception as e: print(f"Error loading {filename}: {e}")

load_textures()

# ================= ИНСТРУМЕНТЫ =================
TOOLS = [
    "grass", "tree", "lake", "house", "wall", "floor", "wood_floor",
    "stone", "concrete", "hydrant", "road", "road_right", "firecar", "ignite"
]
tool_names = {
    "grass": "Трава", "tree": "Дерево", "lake": "Озеро", "house": "Дом", "wall": "Стена",
    "floor": "Пол", "wood_floor": "Дер. пол", "stone": "Камень", "concrete": "Бетон",
    "hydrant": "Гидрант", "firecar": "АЦ (Машина)", "ignite": "Очаг",
    "road": "Дорога (Прямая)", "road_right": "Дорога (Поворот)"
}
current_tool = "grass"
MULTI_CELL_SIZES = {"firecar": (4, 8), "road": (4, 4), "road_right": (5, 5)}
TOOL_SERVER_NAME = {"road": "road_straight", "road_right": "road_turn"}

# ================= UI-ПАНЕЛЬ =================
SECTION_KEYS = ["cars", "objects", "floor", "roads"]
CATEGORIES = {
    "cars": ["firecar"],
    "objects": ["hydrant", "house", "wall", "lake", "tree", "ignite"],
    "floor": ["grass", "floor", "wood_floor", "stone", "concrete"],
    "roads": ["road", "road_right"]
}
SECTION_LABELS = {"cars": "Машины", "objects": "Объекты", "floor": "Пол", "roads": "Дороги"}
dropdown_open_section = None
last_dropdown_buttons, last_section_buttons = [], []
last_save_rect, last_load_rect, last_reset_rect, last_finish_rect = None, None, None, None

def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk: return None
        data += chunk
    return data

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    client.connect((SERVER_IP, SERVER_PORT))
    auth_data = {'type': 'AUTH', 'password': SERVER_PASSWORD, 'role': PLAYER_ROLE}
    msg = json.dumps(auth_data).encode('utf-8')
    client.sendall(struct.pack('>I', len(msg)) + msg)
    client.settimeout(5.0)
    raw_msglen = recv_exact(client, 4)
    msglen = struct.unpack('>I', raw_msglen)[0]
    payload = recv_exact(client, msglen)
    auth_reply = json.loads(payload.decode("utf-8"))
    if auth_reply.get("type") != "AUTH_OK": raise RuntimeError(auth_reply.get("reason", "Ошибка авторизации"))
    client.settimeout(None)
except Exception as e:
    print(f"Ошибка подключения: {e}")
    pygame.quit()
    sys.exit()

def send_to_server(data):
    try:
        msg = json.dumps(data).encode('utf-8')
        client.sendall(struct.pack('>I', len(msg)) + msg)
    except Exception: pass

def receive_thread():
    global server_grid, edit_mode, running_sim
    while True:
        try:
            raw = recv_exact(client, 4)
            if not raw: break
            msglen = struct.unpack('>I', raw)[0]
            data = recv_exact(client, msglen)
            if not data: break
            state = json.loads(data.decode('utf-8'))
            msg_type = state.get('type', '')

            if msg_type == 'STATE_UPDATE':
                server_grid = state['grid']
                edit_mode = state['edit_mode']
                running_sim = state['running_sim']
            
            # === [ИЗМЕНЕНИЕ 2] Вместо "убийства" приложения, отправляем событие в главный поток ===
            elif msg_type == 'START_GAME':
                print("[CLIENT] Получен START_GAME, отправляем событие для переключения...")
                # Создаем событие и помещаем его в очередь Pygame
                pygame.event.post(pygame.event.Event(SWITCH_TO_SANDBOX_EVENT))
                break # Выходим из потока, его работа здесь закончена
        except Exception:
            print("Связь с сервером потеряна")
            break # Выходим из потока при ошибке

server_grid = [[[0, 0, "empty"] for _ in range(COLS)] for _ in range(ROWS)]
edit_mode = True
running_sim = False
threading.Thread(target=receive_thread, daemon=True).start()

def save_map():
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        filepath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON карты", "*.json")], initialdir=MAPS_DIR)
        root.destroy()
        if filepath:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump({"cols": COLS, "rows": ROWS, "grid": server_grid}, f, ensure_ascii=False)
    except Exception as e: print(f"Ошибка сохранения: {e}")

def load_map():
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        filepath = filedialog.askopenfilename(filetypes=[("JSON карты", "*.json")], initialdir=MAPS_DIR)
        root.destroy()
        if filepath:
            with open(filepath, 'r', encoding='utf-8') as f:
                send_to_server({'type': 'LOAD_MAP', 'grid': json.load(f).get("grid")})
    except Exception as e: print(f"Ошибка загрузки: {e}")

def draw_textured_cell(surface, rect, fuel, intensity, ctype, gx, gy):
    x, y = rect.x, rect.y
    if ctype == "firecar_root":
        if "firecar" in TEXTURES: surface.blit(TEXTURES["firecar"], (x, y))
        else: pygame.draw.rect(surface, (200, 30, 30), (x, y, 64, 128))
        return
    elif ctype == "firecar_part": return
    if ctype == "road_straight_root":
        if "road" in TEXTURES: surface.blit(TEXTURES["road"], (x, y))
        else: pygame.draw.rect(surface, (60, 60, 65), (x, y, CELL * 4, CELL * 4))
        return
    elif ctype == "road_straight_part": return
    if ctype == "road_turn_root":
        if "road_right" in TEXTURES: surface.blit(TEXTURES["road_right"], (x, y))
        else: pygame.draw.rect(surface, (60, 60, 65), (x, y, CELL * 5, CELL * 5))
        return
    elif ctype == "road_turn_part": return

    if intensity > 8:
        scaled = pygame.transform.scale(fire_texture, (CELL, CELL))
        offset_x = random.randint(-3, 3)
        offset_y = -random.randint(0, 5) - int(intensity // 10)
        surface.blit(scaled, (x + offset_x, y + offset_y))
        return

    texture_key = ctype.replace("_root", "")
    if texture_key.endswith("_part"): return
    if texture_key in TEXTURES:
        surface.blit(TEXTURES[texture_key], rect)
    else:
        pygame.draw.rect(surface, (30, 25, 20), rect)

def draw_grid():
    for y in range(ROWS):
        for x in range(COLS):
            fuel, intensity, ctype = server_grid[y][x]
            rect = pygame.Rect(x * CELL, y * CELL, CELL, CELL)
            draw_textured_cell(screen, rect, fuel, intensity, ctype, x, y)

def draw_multi_cell_preview():
    if not edit_mode or current_tool not in MULTI_CELL_SIZES: return
    mx, my = pygame.mouse.get_pos()
    if mx >= GRID_WIDTH: return
    gx, gy = mx // CELL, my // CELL
    w, h = MULTI_CELL_SIZES[current_tool]
    fits = (0 <= gx <= COLS - w) and (0 <= gy <= ROWS - h)
    pw, ph = w * CELL, h * CELL
    preview_surf = pygame.Surface((pw, ph), pygame.SRCALPHA)
    if fits:
        preview_surf.fill((100, 255, 100, 45))
        border_color = (80, 255, 80)
        if current_tool in TEXTURES:
            ghost = TEXTURES[current_tool].copy()
            ghost.set_alpha(120)
            preview_surf.blit(ghost, (0, 0))
    else:
        preview_surf.fill((255, 80, 80, 50))
        border_color = (255, 60, 60)
    screen.blit(preview_surf, (gx * CELL, gy * CELL))
    pygame.draw.rect(screen, border_color, (gx * CELL, gy * CELL, pw, ph), 2)

def draw_ui():
    # ... (код отрисовки UI остается без изменений, он длинный, поэтому я его убрал, чтобы не загромождать)
    # ... Скопируйте ваш существующий код draw_ui сюда ...
    # ... Это важно, не забудьте!
    global last_dropdown_buttons, last_section_buttons, last_save_rect, last_load_rect, last_reset_rect, last_finish_rect
    last_dropdown_buttons, last_section_buttons = [], []
    pygame.draw.rect(screen, (25, 25, 35), (GRID_WIDTH, 0, PANEL_WIDTH, HEIGHT))
    pygame.draw.line(screen, (50, 50, 60), (GRID_WIDTH, 0), (GRID_WIDTH, HEIGHT), 3)
    mouse_pos, cur_y = pygame.mouse.get_pos(), 18
    for idx, key in enumerate(SECTION_KEYS):
        rect = pygame.Rect(GRID_WIDTH + 15, cur_y, PANEL_WIDTH - 30, 36)
        last_section_buttons.append({"key": key, "rect": rect})
        active, hover = (dropdown_open_section == key), rect.collidepoint(mouse_pos)
        color = (70, 100, 170) if active else (75, 85, 120) if hover else (65, 75, 110)
        pygame.draw.rect(screen, color, rect, border_radius=8)
        txt = small_font.render(SECTION_LABELS[key], True, (255, 255, 255))
        screen.blit(txt, (rect.x + 12, rect.y + 8))
        cur_y += 36
        if dropdown_open_section == key:
            cur_y += 8
            for i, item in enumerate(CATEGORIES[key]):
                item_rect = pygame.Rect(GRID_WIDTH + 20, cur_y, PANEL_WIDTH - 40, 30)
                is_selected, item_hover = (current_tool == item), item_rect.collidepoint(mouse_pos)
                bg_color = (110, 130, 180) if is_selected else (95, 95, 140) if item_hover else (75, 80, 110)
                pygame.draw.rect(screen, bg_color, item_rect, border_radius=6)
                last_dropdown_buttons.append({"rect": item_rect, "tool": item, "section": key})
                label = tool_names.get(item, item)
                screen.blit(small_font.render(label, True, (255, 255, 255)), (item_rect.x + 8, item_rect.y + 6))
                cur_y += 30 + 6
        cur_y += 8
    cur_y += 16
    last_save_rect = pygame.Rect(GRID_WIDTH + 15, cur_y, (PANEL_WIDTH - 40) // 2, 36)
    last_load_rect = pygame.Rect(last_save_rect.right + 10, cur_y, (PANEL_WIDTH - 40) // 2, 36)
    pygame.draw.rect(screen, (50, 160, 80) if last_save_rect.collidepoint(mouse_pos) else (40, 120, 60), last_save_rect, border_radius=8)
    screen.blit(small_font.render("Сохранить", True, (255,255,255)), small_font.render("Сохранить", True, (255,255,255)).get_rect(center=last_save_rect.center))
    pygame.draw.rect(screen, (50, 100, 180) if last_load_rect.collidepoint(mouse_pos) else (35, 75, 140), last_load_rect, border_radius=8)
    screen.blit(small_font.render("Загрузить", True, (255,255,255)), small_font.render("Загрузить", True, (255,255,255)).get_rect(center=last_load_rect.center))
    cur_y += 44
    last_reset_rect = pygame.Rect(GRID_WIDTH + 15, cur_y, PANEL_WIDTH - 30, 38)
    pygame.draw.rect(screen, (255, 70, 70) if last_reset_rect.collidepoint(mouse_pos) else (190, 50, 50), last_reset_rect, border_radius=9)
    screen.blit(small_font.render("ОЧИСТИТЬ ВСЁ", True, (255,255,255)), small_font.render("ОЧИСТИТЬ ВСЁ", True, (255,255,255)).get_rect(center=last_reset_rect.center))
    cur_y += 50
    last_finish_rect = pygame.Rect(GRID_WIDTH + 15, cur_y, PANEL_WIDTH - 30, 42)
    hover_f = last_finish_rect.collidepoint(mouse_pos)
    pygame.draw.rect(screen, (255, 180, 30) if hover_f else (210, 140, 20), last_finish_rect, border_radius=9)
    screen.blit(font.render("ЗАВЕРШИТЬ", True, (30,30,30)), font.render("ЗАВЕРШИТЬ", True, (30,30,30)).get_rect(center=last_finish_rect.center))
# ================= ГЛАВНЫЙ ЦИКЛ =================
running = True
should_switch = False

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        # === [ИЗМЕНЕНИЕ 3] Ловим наше кастомное событие ===
        if event.type == SWITCH_TO_SANDBOX_EVENT:
            should_switch = True
            running = False # Даем команду на выход из главного цикла
            break # Прерываем обработку других событий

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE: send_to_server({'type': 'SPACE'})
            if event.key == pygame.K_r: send_to_server({'type': 'R'})
        
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if mx < GRID_WIDTH:
                gx, gy = mx // CELL, my // CELL
                if current_tool in MULTI_CELL_SIZES and edit_mode:
                    w, h = MULTI_CELL_SIZES[current_tool]
                    if 0 <= gx <= COLS - w and 0 <= gy <= ROWS - h:
                        server_tool = TOOL_SERVER_NAME.get(current_tool, current_tool)
                        send_to_server({'type': 'CLICK', 'x': gx, 'y': gy, 'tool': server_tool})
            else:
                for sb in last_section_buttons:
                    if sb['rect'].collidepoint(event.pos): dropdown_open_section = sb['key'] if dropdown_open_section != sb['key'] else None
                for db in last_dropdown_buttons:
                    if db['rect'].collidepoint(event.pos): current_tool = db['tool']
                if last_save_rect and last_save_rect.collidepoint(event.pos): save_map()
                if last_load_rect and last_load_rect.collidepoint(event.pos): load_map()
                if last_reset_rect and last_reset_rect.collidepoint(event.pos): send_to_server({'type': 'R'})
                if last_finish_rect and last_finish_rect.collidepoint(event.pos):
                    send_to_server({'type': 'HOST_READY', 'final_grid': server_grid})

    if not running: break

    if edit_mode and pygame.mouse.get_pressed()[0]:
        mx, my = pygame.mouse.get_pos()
        if mx < GRID_WIDTH and current_tool not in MULTI_CELL_SIZES:
            gx, gy = mx // CELL, my // CELL
            if 0 <= gx < COLS and 0 <= gy < ROWS:
                send_to_server({'type': 'CLICK', 'x': gx, 'y': gy, 'tool': current_tool})

    screen.fill((12, 22, 45))
    draw_grid()
    draw_multi_cell_preview()
    draw_ui()
    pygame.display.flip()
    clock.tick(FPS)

# === [ИЗМЕНЕНИЕ 4] Вся логика переключения теперь здесь, ПОСЛЕ выхода из главного цикла ===
if should_switch:
    print("Корректно вышли из цикла, запускаем game_sandbox.py...")
    pygame.quit() # Теперь безопасно закрывать Pygame
    env = os.environ.copy()
    env["SERVER_IP"] = SERVER_IP
    env["SERVER_PORT"] = str(SERVER_PORT)
    env["SERVER_PASSWORD"] = SERVER_PASSWORD
    env["PLAYER_ROLE"] = PLAYER_ROLE
    subprocess.Popen([sys.executable, os.path.join(BASE_DIR, "game_sandbox.py")], env=env)
    sys.exit(0) # Используем sys.exit для более чистого выхода
else:
    client.close()
    pygame.quit()
    sys.exit()