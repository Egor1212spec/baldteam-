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
PANEL_WIDTH = 300
WIDTH = GRID_WIDTH + PANEL_WIDTH
HEIGHT = 704
COLS = GRID_WIDTH // CELL
ROWS = HEIGHT // CELL
FPS = 30

def get_ui_font(size, bold=False):
    font_paths = ["C:/Windows/Fonts/arial.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return pygame.font.Font(path, size)
            except Exception:
                pass
    return pygame.font.SysFont("arial", size, bold=bold)

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

def draw_dispatcher_panel():
    # ... твой код панели без изменений ...
    panel_x = GRID_WIDTH
    pygame.draw.rect(screen, (20, 30, 50), (panel_x, 0, PANEL_WIDTH, HEIGHT))
    pygame.draw.line(screen, (0, 150, 255), (panel_x, 0), (panel_x, HEIGHT), 2)

    y = 20
    title = font_bold.render("СЛУЖБА ДИСПЕТЧЕРА", True, (0, 255, 255))
    screen.blit(title, (panel_x + 35, y))
    
    y += 50
    pygame.draw.rect(screen, (40, 50, 80), (panel_x + 10, y, PANEL_WIDTH - 20, 110), border_radius=5)
    
    services = [
        ("ПОЖАРНАЯ ОХРАНА", "101", (255, 80, 80)),
        ("ПОЛИЦИЯ", "102", (100, 150, 255)),
        ("СКОРАЯ ПОМОЩЬ", "103", (100, 255, 100))
    ]
    yy = y + 10
    for name, num, col in services:
        screen.blit(small_font.render(name, True, (200, 200, 200)), (panel_x + 20, yy))
        screen.blit(font_bold.render(num, True, col), (panel_x + PANEL_WIDTH - 50, yy - 2))
        yy += 32

    y += 130
    screen.blit(font_bold.render("ТЕХНИКА В РЕЗЕРВЕ:", True, (255, 255, 255)), (panel_x + 15, y))
    y += 35
    
    trucks = ["АЦ-40 (Пожарная автоцистерна)", "АЛ-30 (Автолестница)", "АНР (Насосно-рукавный)",
              "АСА (Аварийно-спасательный)", "АГ (Газодымозащитный)"]
    for truck in trucks:
        pygame.draw.circle(screen, (0, 200, 0), (panel_x + 25, y + 10), 5)
        screen.blit(small_font.render(truck, True, (220, 220, 220)), (panel_x + 40, y))
        y += 28

    y = HEIGHT - 150
    burning_count = sum(cell[1] > 8 for row in server_grid for cell in row)
    color = (255, 100, 0) if burning_count > 0 else (100, 255, 100)
    status_msg = "ВЫЗОВ АКТИВЕН" if burning_count > 0 else "ВЫЗОВОВ НЕТ"
    
    pygame.draw.rect(screen, (10, 15, 30), (panel_x + 10, y, PANEL_WIDTH - 20, 80), border_radius=10)
    pygame.draw.rect(screen, color, (panel_x + 10, y, PANEL_WIDTH - 20, 80), width=2, border_radius=10)
    
    status_surf = font_bold.render(status_msg, True, color)
    screen.blit(status_surf, status_surf.get_rect(center=(panel_x + PANEL_WIDTH//2, y + 25)))
    
    count_surf = small_font.render(f"Очагов горения: {burning_count}", True, (200, 200, 200))
    screen.blit(count_surf, count_surf.get_rect(center=(panel_x + PANEL_WIDTH//2, y + 55)))

    time_str = pygame.time.get_ticks() // 1000
    time_surf = small_font.render(f"ВРЕМЯ СМЕНЫ: {time_str} сек", True, (100, 100, 100))
    screen.blit(time_surf, (panel_x + 20, HEIGHT - 30))

# ================= ЦИКЛ =================
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            try:
                sock.sendall(struct.pack(">I", len(b'{"type":"SPACE"}')) + b'{"type":"SPACE"}')
            except:
                pass

    screen.fill((5, 10, 20))
    draw_grid()
    draw_dispatcher_panel()
    pygame.display.flip()
    clock.tick(FPS)

pygame.quit()
sock.close()