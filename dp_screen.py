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
PLAYER_ROLE = "dispatcher"

CELL = 16
GRID_WIDTH = 960
PANEL_WIDTH = 340   # чуть шире для новых кнопок
WIDTH = GRID_WIDTH + PANEL_WIDTH
HEIGHT = 704
COLS = GRID_WIDTH // CELL
ROWS = HEIGHT // CELL
FPS = 30

# ================= МАШИНЫ =================
TRUCKS = [
    "АЦ-40", "АЦ-3,2-40/4", "АЦ-6,0-40", "ПНС-110",
    "АР-2", "АНР-3,0-100", "АЛ-30", "АЛ-50"
]

def get_ui_font(size, bold=False):
    font_paths = ["C:/Windows/Fonts/arial.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]
    for path in font_paths:
        if os.path.exists(path):
            try: return pygame.font.Font(path, size)
            except: pass
    return pygame.font.SysFont("arial", size, bold=bold)

def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk: return None
        data += chunk
    return data

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("ПУЛЬТ ДИСПЕТЧЕРА 01")
clock = pygame.time.Clock()

font_bold = get_ui_font(20, True)
small_font = get_ui_font(16)
tiny_font = get_ui_font(14)

# ================= ТЕКСТУРЫ И КАРТА (без изменений) =================
TEXTURES = {}
fire_texture = None
server_grid = [[[0, 0, "empty"] for _ in range(COLS)] for _ in range(ROWS)]
running_sim = False
# ================= PYGAME INIT =================
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption(f"ПУЛЬТ ДИСПЕТЧЕРА 01")
clock = pygame.time.Clock()

font_main = get_ui_font(18)
font_bold = get_ui_font(20, True)
font_huge = get_ui_font(36, True)
small_font = get_ui_font(14)

# ================= ТЕКСТУРЫ =================
TEXTURES = {}
fire_texture = None

def load_textures():
    global TEXTURES, fire_texture
    try:
        fire_texture = pygame.image.load(os.path.join(BASE_DIR, "fire.png")).convert_alpha()
    except:
        fire_texture = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
        fire_texture.fill((255, 100, 0, 180))
    
    tex_dir = os.path.join(BASE_DIR, "textures")
    if os.path.exists(tex_dir):
        for f in os.listdir(tex_dir):
            if f.lower().endswith((".png", ".jpg", ".jpeg")):
                key = os.path.splitext(f)[0].lower()
                try:
                    img = pygame.image.load(os.path.join(tex_dir, f)).convert_alpha()
                    if key == "firecar":
                        TEXTURES[key] = pygame.transform.scale(img, (64, 128))
                    elif "road" in key:
                        TEXTURES[key] = pygame.transform.scale(img, (CELL*4, CELL*4))
                    else:
                        TEXTURES[key] = pygame.transform.scale(img, (CELL, CELL))
                except:
                    pass

# ================= СЕТЬ И КАРТА =================
# Создаём сетку ПЕРЕД загрузкой карты
server_grid = [[[0, 0, "empty"] for _ in range(COLS)] for _ in range(ROWS)]
running_sim = False

# Загружаем карту, которую передал waiting_screen.py
grid_file = os.getenv("GRID_FILE")
if grid_file and os.path.exists(grid_file):
    try:
        with open(grid_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        for y in range(min(ROWS, len(loaded))):
            for x in range(min(COLS, len(loaded[y]))):
                if len(loaded[y][x]) >= 3:
                    server_grid[y][x] = loaded[y][x][:]   # копия списка
        print(f"[DP] Карта успешно загружена из {grid_file} ({len(loaded)}x{len(loaded[0])})")
    except Exception as e:
        print(f"[DP] Ошибка загрузки карты: {e}")

# Загружаем текстуры (теперь безопасно)
load_textures()

# ================= СЕТЬ =================
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
connected = False

try:
    sock.connect((SERVER_IP, SERVER_PORT))
    auth = {"type": "AUTH", "password": SERVER_PASSWORD, "role": PLAYER_ROLE}
    msg = json.dumps(auth).encode("utf-8")
    sock.sendall(struct.pack(">I", len(msg)) + msg)
    connected = True
    print(f"[DP] Подключён к серверу как {PLAYER_ROLE.upper()}")
except Exception as e:
    print(f"[DP] Ошибка подключения: {e}")

def receive_thread():
    global server_grid, running_sim
    while True:
        try:
            raw = recv_exact(sock, 4)
            if not raw: break
            mlen = struct.unpack(">I", raw)[0]
            data = json.loads(recv_exact(sock, mlen).decode("utf-8"))
            if data.get("type") == "STATE_UPDATE":
                server_grid = data["grid"]
                running_sim = data.get("running_sim", False)
        except:
            break

if connected:
    threading.Thread(target=receive_thread, daemon=True).start()

# ================= ОТРИСОВКА (без изменений) =================
def draw_grid():
    for y in range(ROWS):
        for x in range(COLS):
            fuel, intensity, ctype = server_grid[y][x]
            rect = pygame.Rect(x * CELL, y * CELL, CELL, CELL)
            
            if intensity > 8:
                scaled = pygame.transform.scale(fire_texture, (CELL, CELL))
                screen.blit(scaled, (rect.x + random.randint(-2,2), rect.y - random.randint(2,5)))
                continue

            t_key = ctype.replace("_root", "").replace("_part", "")
            if t_key in TEXTURES:
                if ("road" in ctype or "firecar" in ctype) and "_root" in ctype:
                    screen.blit(TEXTURES[t_key], rect)
                else:
                    screen.blit(TEXTURES[t_key], rect)
            else:
                if ctype != "empty":
                    pygame.draw.rect(screen, (40, 40, 45), rect)

last_truck_buttons = []   # для кликов

def draw_dispatcher_panel():
    global last_truck_buttons
    last_truck_buttons = []
    panel_x = GRID_WIDTH
    pygame.draw.rect(screen, (20, 30, 50), (panel_x, 0, PANEL_WIDTH, HEIGHT))
    pygame.draw.line(screen, (0, 150, 255), (panel_x, 0), (panel_x, HEIGHT), 2)

    y = 20
    title = font_bold.render("СЛУЖБА ДИСПЕТЧЕРА", True, (0, 255, 255))
    screen.blit(title, (panel_x + 35, y))
    y += 60

    # === НОВЫЙ БЛОК: Вызвать технику ===
    header = font_bold.render("ВЫЗВАТЬ ТЕХНИКУ:", True, (255, 220, 80))
    screen.blit(header, (panel_x + 20, y))
    y += 45

    for truck in TRUCKS:
        # фон строки
        row_rect = pygame.Rect(panel_x + 15, y, PANEL_WIDTH - 30, 42)
        pygame.draw.rect(screen, (35, 45, 70), row_rect, border_radius=6)

        # название машины
        screen.blit(small_font.render(truck, True, (255, 255, 255)), (panel_x + 25, y + 12))

        # кнопка "Отправить"
        btn_rect = pygame.Rect(panel_x + PANEL_WIDTH - 115, y + 6, 92, 30)
        mouse_pos = pygame.mouse.get_pos()
        color = (0, 200, 100) if btn_rect.collidepoint(mouse_pos) else (0, 160, 80)
        pygame.draw.rect(screen, color, btn_rect, border_radius=6)
        screen.blit(tiny_font.render("Отправить", True, (255,255,255)), (btn_rect.x + 8, btn_rect.y + 8))

        last_truck_buttons.append({"rect": btn_rect, "truck": truck})
        y += 48

    # остальная панель (статус пожара, техника в резерве и т.д.) — оставь как было
    # ... (твой старый код status, время и т.д.)

# ================= ЦИКЛ (добавляем обработку кнопок) =================
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for btn in last_truck_buttons:
                if btn["rect"].collidepoint(event.pos):
                    # Отправляем на сервер
                    try:
                        data = {"type": "DEPLOY_TRUCK", "truck": btn["truck"]}
                        msg = json.dumps(data).encode("utf-8")
                        sock.sendall(struct.pack(">I", len(msg)) + msg)
                        print(f"[DISPATCHER] Отправлена техника: {btn['truck']}")
                    except:
                        pass

    screen.fill((5, 10, 20))
    draw_grid()
    draw_dispatcher_panel()
    pygame.display.flip()
    clock.tick(FPS)

pygame.quit()
sock.close()