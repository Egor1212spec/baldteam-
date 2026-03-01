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

def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk: return None
        data += chunk
    return data

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption(f"Симуляция пожара [{SERVER_IP}] [{ROLE_LABELS.get(PLAYER_ROLE, PLAYER_ROLE)}]")
clock = pygame.time.Clock()
font = get_ui_font(19)
big_font = get_ui_font(32, bold=True)
small_font = get_ui_font(16)

TEXTURE_DIR = os.path.join(BASE_DIR, "textures")
TEXTURES = {}
fire_texture = None

def load_textures():
    global TEXTURES, fire_texture
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    TEXTURES = {}
    try:
        fire_texture = pygame.image.load(os.path.join(BASE_DIR, "fire.png")).convert_alpha()
    except Exception:
        fire_texture = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
        fire_texture.fill((255, 100, 0, 180))
    for filename in os.listdir(TEXTURE_DIR):
        if not filename.lower().endswith((".png", ".jpg", ".jpeg")): continue
        key = os.path.splitext(filename)[0].lower()
        path = os.path.join(TEXTURE_DIR, filename)
        try:
            img = pygame.image.load(path).convert_alpha()
            if key == "firecar": TEXTURES["firecar"] = pygame.transform.scale(img, (64, 128))
            elif key in ("road", "road_straight"): TEXTURES["road"] = pygame.transform.scale(img, (CELL * 4, CELL * 4))
            elif key in ("road_right", "road_turn"): TEXTURES["road_right"] = pygame.transform.scale(img, (CELL * 5, CELL * 5))
            else: TEXTURES[key] = pygame.transform.scale(img, (CELL, CELL))
        except Exception: pass

load_textures()

server_grid = [[[0, 0, "empty"] for _ in range(COLS)] for _ in range(ROWS)]
edit_mode = False
running_sim = False # Начинаем с паузы

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
connected = False
try:
    sock.connect((SERVER_IP, SERVER_PORT))
    auth_data = {"type": "AUTH", "password": SERVER_PASSWORD, "role": PLAYER_ROLE}
    payload = json.dumps(auth_data).encode("utf-8")
    sock.sendall(struct.pack(">I", len(payload)) + payload)
    sock.settimeout(5.0)
    raw_len = recv_exact(sock, 4)
    if raw_len:
        msg_len = struct.unpack(">I", raw_len)[0]
        reply = recv_exact(sock, msg_len)
        if reply and json.loads(reply.decode("utf-8")).get("type") == "AUTH_OK":
            connected = True
    sock.settimeout(None)
except Exception as e:
    print(f"[SANDBOX] Ошибка подключения: {e}")

def receive_thread():
    global server_grid, edit_mode, running_sim
    while True:
        try:
            raw = recv_exact(sock, 4)
            if not raw: break
            msglen = struct.unpack(">I", raw)[0]
            data = recv_exact(sock, msglen)
            if not data: break
            msg = json.loads(data.decode("utf-8"))
            if msg.get("type") == "STATE_UPDATE":
                server_grid = msg["grid"]
                running_sim = msg.get("running_sim", False)
        except Exception:
            print("[SANDBOX] Связь с сервером потеряна")
            break

if connected:
    threading.Thread(target=receive_thread, daemon=True).start()

def draw_textured_cell(surface, rect, fuel, intensity, ctype, gx, gy):
    # (Код этой функции не меняется, скопируйте свой)
    x, y = rect.x, rect.y
    if ctype == "firecar_root":
        if "firecar" in TEXTURES: surface.blit(TEXTURES["firecar"], (x, y))
        return
    if ctype.startswith("road_straight"):
        if ctype.endswith("_root") and "road" in TEXTURES: surface.blit(TEXTURES["road"], (x, y))
        return
    if ctype.startswith("road_turn"):
        if ctype.endswith("_root") and "road_right" in TEXTURES: surface.blit(TEXTURES["road_right"], (x, y))
        return
    if intensity > 8:
        scaled = pygame.transform.scale(fire_texture, (CELL, CELL))
        offset_x = random.randint(-3, 3)
        offset_y = -random.randint(0, 5) - int(intensity // 10)
        surface.blit(scaled, (x + offset_x, y + offset_y))
        return
    texture_key = ctype.replace("_root", "").replace("_part", "")
    if texture_key in TEXTURES:
        surface.blit(TEXTURES[texture_key], rect)
    else:
        pygame.draw.rect(surface, (30,25,20), rect)


def draw_grid():
    for y in range(ROWS):
        for x in range(COLS):
            fuel, intensity, ctype = server_grid[y][x]
            rect = pygame.Rect(x * CELL, y * CELL, CELL, CELL)
            draw_textured_cell(screen, rect, fuel, intensity, ctype, x, y)

def draw_panel():
    pygame.draw.rect(screen, (25, 25, 35), (GRID_WIDTH, 0, PANEL_WIDTH, HEIGHT))
    pygame.draw.line(screen, (50, 50, 60), (GRID_WIDTH, 0), (GRID_WIDTH, HEIGHT), 3)
    title = big_font.render("СИМУЛЯЦИЯ", True, (255, 200, 60))
    screen.blit(title, (GRID_WIDTH + 30, 30))
    status_text = "Пауза (ПРОБЕЛ)" if not running_sim else "Огонь активен"
    status_color = (255, 200, 80) if not running_sim else (100, 255, 100)
    screen.blit(font.render(status_text, True, status_color), (GRID_WIDTH + 20, 120))
    hint = small_font.render("SPACE — старт/пауза | ESC — выход", True, (120, 130, 150))
    screen.blit(hint, (GRID_WIDTH + 20, HEIGHT - 40))

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
            running = False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            try:
                msg = json.dumps({'type': 'SPACE'}).encode('utf-8')
                sock.sendall(struct.pack('>I', len(msg)) + msg)
            except Exception: pass

    screen.fill((12, 22, 45))
    draw_grid()
    draw_panel()
    pygame.display.flip()
    clock.tick(FPS)

sock.close()
pygame.quit()
sys.exit()