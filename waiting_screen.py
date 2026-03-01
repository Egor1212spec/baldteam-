import os
import sys
import json
import socket
import struct
import subprocess
import threading
import time

import pygame

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if load_dotenv is not None:
    load_dotenv(os.path.join(BASE_DIR, ".env"))


def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def run_waiting_screen():
    server_ip = os.getenv("SERVER_IP", "127.0.0.1")
    server_port = int(os.getenv("SERVER_PORT", "5555"))
    password = os.getenv("SERVER_PASSWORD", "my_super_password")
    player_role = os.getenv("PLAYER_ROLE", "rtp").lower()

    print(f"[WAITING] Запущен с ролью: {player_role.upper()}")

    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("Песочница пожара — Ожидание игры")
    clock = pygame.time.Clock()

    font_big = pygame.font.SysFont("arial", 48, bold=True)
    font = pygame.font.SysFont("arial", 28)
    font_small = pygame.font.SysFont("arial", 20)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)

    status_text = "Подключение к серверу..."
    connected = False
    game_started = False
    received_grid = None
    dots_timer = 0

    try:
        sock.connect((server_ip, server_port))
        auth_data = {"type": "AUTH", "password": password, "role": player_role}
        payload = json.dumps(auth_data).encode("utf-8")
        sock.sendall(struct.pack(">I", len(payload)) + payload)

        raw_len = recv_exact(sock, 4)
        if raw_len:
            msg_len = struct.unpack(">I", raw_len)[0]
            reply = recv_exact(sock, msg_len)
            if reply:
                auth_reply = json.loads(reply.decode("utf-8"))
                if auth_reply.get("type") == "AUTH_OK":
                    connected = True
                    status_text = f"Подключено! Роль: {player_role.upper()}"
                    print(f"[WAITING] Успешная авторизация как {player_role.upper()}")
                else:
                    status_text = "Ошибка авторизации: " + auth_reply.get("reason", "неизвестно")
    except Exception as e:
        status_text = f"Ошибка подключения: {e}"
        print(f"[WAITING] Ошибка подключения: {e}")

    def listen_server():
        nonlocal game_started, received_grid
        sock.settimeout(None)
        while not game_started:
            try:
                raw_len = recv_exact(sock, 4)
                if not raw_len: continue
                msg_len = struct.unpack(">I", raw_len)[0]
                data = recv_exact(sock, msg_len)
                if data:
                    msg = json.loads(data.decode("utf-8"))
                    if msg.get("type") == "START_GAME":
                        received_grid = msg.get("grid")
                        game_started = True
                        print("[WAITING] Получен START_GAME! Карта получена.")
            except Exception as e:
                print(f"[WAITING] Ошибка приёма: {e}")
                break

    if connected:
        threading.Thread(target=listen_server, daemon=True).start()

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sock.close()
                sys.exit(0)

        screen.fill((18, 24, 38))

        dots_timer += 1
        dots = "." * ((dots_timer // 20) % 4)

        # Заголовок
        title_surf = font_big.render("ОЖИДАНИЕ ИГРЫ", True, (240, 244, 255))
        screen.blit(title_surf, title_surf.get_rect(center=(400, 180)))

        # Статус
        status_surf = font.render(status_text, True, (170, 188, 220))
        screen.blit(status_surf, status_surf.get_rect(center=(400, 260)))

        if connected and not game_started:
            # Сервер
            info_surf = font_small.render(f"Сервер: {server_ip}:{server_port}", True, (140, 200, 140))
            screen.blit(info_surf, info_surf.get_rect(center=(400, 320)))

            # Ожидание карты
            wait_surf = font.render(f"Хост создаёт карту{dots}", True, (170, 188, 220))
            screen.blit(wait_surf, wait_surf.get_rect(center=(400, 380)))

            # Подсказка
            stay_surf = font.render("Оставайтесь на связи!", True, (120, 220, 140))
            screen.blit(stay_surf, stay_surf.get_rect(center=(400, 430)))

        if game_started:
            go_surf = font_big.render("ИГРА НАЧИНАЕТСЯ!", True, (90, 220, 120))
            screen.blit(go_surf, go_surf.get_rect(center=(400, 350)))
            pygame.display.flip()
            pygame.time.wait(800)

            # ==================== ЗАПУСК НУЖНОГО СКРИПТА ====================
            pygame.quit()
            time.sleep(0.6)

            script_name = "dp_screen.py" if player_role == "dispatcher" else "game_sandbox.py"
            script_path = os.path.join(BASE_DIR, script_name)

            env = os.environ.copy()
            env["SERVER_IP"] = server_ip
            env["SERVER_PORT"] = str(server_port)
            env["SERVER_PASSWORD"] = password
            env["PLAYER_ROLE"] = player_role

            if received_grid:
                grid_path = os.path.join(BASE_DIR, "_temp_grid.json")
                with open(grid_path, "w", encoding="utf-8") as f:
                    json.dump(received_grid, f)
                env["GRID_FILE"] = grid_path
                print(f"[WAITING] Карта сохранена в {grid_path}")

            print(f"[WAITING] Запускаем → {script_name} (роль {player_role.upper()})")

            try:
                if sys.platform == "win32":
                    p = subprocess.Popen(
                        [sys.executable, script_path],
                        env=env,
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                else:
                    p = subprocess.Popen([sys.executable, script_path], env=env)
                print(f"[WAITING] subprocess запущен (PID={p.pid})")
            except Exception as e:
                print(f"[ERROR] Не удалось запустить {script_name}: {e}")

            sock.close()
            return

        pygame.display.flip()
        clock.tick(30)


if __name__ == "__main__":
    run_waiting_screen()