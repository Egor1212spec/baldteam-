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
    received_grid = None  # будем хранить карту от сервера
    dots_timer = 0

    try:
        sock.connect((server_ip, server_port))

        auth_data = {
            "type": "AUTH",
            "password": password,
            "role": player_role
        }
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
                    print(f"[WAIT] Успешно подключился как {player_role}")
                else:
                    status_text = "Ошибка авторизации: " + auth_reply.get("reason", "неизвестно")
    except Exception as e:
        status_text = f"Ошибка подключения: {e}"

    def listen_server():
        nonlocal game_started, received_grid
        sock.settimeout(None)  # блокирующий режим
        while not game_started:
            try:
                raw_len = recv_exact(sock, 4)
                if not raw_len:
                    continue
                msg_len = struct.unpack(">I", raw_len)[0]
                data = recv_exact(sock, msg_len)
                if data:
                    msg = json.loads(data.decode("utf-8"))
                    msg_type = msg.get("type", "")

                    if msg_type == "START_GAME":
                        received_grid = msg.get("grid")
                        game_started = True
                        print("[WAIT] Получена команда START_GAME!")
                    # Игнорируем STATE_UPDATE — мы на экране ожидания
            except socket.timeout:
                time.sleep(0.1)
            except Exception as e:
                print(f"[WAIT] Ошибка приёма: {e}")
                break

    if connected:
        listener_thread = threading.Thread(target=listen_server, daemon=True)
        listener_thread.start()

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sock.close()
                sys.exit(0)

        screen.fill((18, 24, 38))

        # Анимированные точки
        dots_timer += 1
        dots = "." * ((dots_timer // 20) % 4)

        title_surf = font_big.render("ОЖИДАНИЕ ИГРЫ", True, (240, 244, 255))
        title_rect = title_surf.get_rect(center=(400, 180))
        screen.blit(title_surf, title_rect)

        status_surf = font.render(status_text, True, (170, 188, 220))
        status_rect = status_surf.get_rect(center=(400, 260))
        screen.blit(status_surf, status_rect)

        if connected and not game_started:
            info_surf = font_small.render(f"Сервер: {server_ip}:{server_port}", True, (140, 200, 140))
            screen.blit(info_surf, info_surf.get_rect(center=(400, 320)))

            wait_surf = font.render(f"Хост создаёт карту{dots}", True, (170, 188, 220))
            screen.blit(wait_surf, wait_surf.get_rect(center=(400, 380)))

            stay_surf = font.render("Оставайтесь на связи!", True, (120, 220, 140))
            screen.blit(stay_surf, stay_surf.get_rect(center=(400, 430)))

        if game_started:
            go_surf = font_big.render("ИГРА НАЧИНАЕТСЯ!", True, (90, 220, 120))
            screen.blit(go_surf, go_surf.get_rect(center=(400, 350)))
            pygame.display.flip()
            pygame.time.wait(1200)
            pygame.quit()
            sock.close()

            # Запускаем game_sandbox.py с передачей карты и настроек
            env = os.environ.copy()
            env["SERVER_IP"] = server_ip
            env["SERVER_PORT"] = str(server_port)
            env["SERVER_PASSWORD"] = password
            env["PLAYER_ROLE"] = player_role
            if received_grid:
                # Сохраняем карту во временный файл (JSON в env может быть слишком большим)
                grid_path = os.path.join(BASE_DIR, "_temp_grid.json")
                with open(grid_path, "w", encoding="utf-8") as f:
                    json.dump(received_grid, f)
                env["GRID_FILE"] = grid_path

            subprocess.Popen(
                [sys.executable, os.path.join(BASE_DIR, "game_sandbox.py")],
                env=env
            )
            return

        pygame.display.flip()
        clock.tick(30)


if __name__ == "__main__":
    run_waiting_screen()