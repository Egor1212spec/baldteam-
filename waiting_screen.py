import os
import sys
import json
import socket
import struct
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
    # Читаем настройки из окружения (передаются из client_menu.py)
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

    # Подключаемся к серверу
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)

    status_text = "Подключение к серверу..."
    connected = False
    game_started = False

    try:
        sock.connect((server_ip, server_port))

        # Авторизация
        auth_data = {
            "type": "AUTH",
            "password": password,
            "role": player_role
        }
        payload = json.dumps(auth_data).encode("utf-8")
        sock.sendall(struct.pack(">I", len(payload)) + payload)

        # Ждём ответ
        raw_len = recv_exact(sock, 4)
        if raw_len:
            msg_len = struct.unpack(">I", raw_len)[0]
            reply = recv_exact(sock, msg_len)
            if reply:
                auth_reply = json.loads(reply.decode("utf-8"))
                if auth_reply.get("type") == "AUTH_OK":
                    connected = True
                    status_text = f"Подключено! Роль: {player_role.upper()}"
                    print(f"[CLIENT] Успешно подключился как {player_role}")
                else:
                    status_text = "Ошибка авторизации: " + auth_reply.get("reason", "неизвестно")
    except Exception as e:
        status_text = f"Ошибка подключения: {e}"

    # Поток для приёма сообщений от сервера (чтобы не блокировать UI)
    def listen_server():
        nonlocal game_started
        sock.settimeout(0.5)
        while not game_started:
            try:
                raw_len = recv_exact(sock, 4)
                if not raw_len:
                    continue
                msg_len = struct.unpack(">I", raw_len)[0]
                data = recv_exact(sock, msg_len)
                if data:
                    msg = json.loads(data.decode("utf-8"))
                    if msg.get("type") == "START_GAME":
                        game_started = True
                        print("[CLIENT] Получена команда START_GAME! Запускаем игру...")
            except:
                time.sleep(0.1)

    listener_thread = threading.Thread(target=listen_server, daemon=True)
    listener_thread.start()

    # Основной цикл отрисовки
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sock.close()
                sys.exit(0)

        screen.fill((18, 24, 38))

        screen.blit(font_big.render("ОЖИДАНИЕ ИГРЫ", True, (240, 244, 255)), (190, 160))
        screen.blit(font.render(status_text, True, (170, 188, 220)), (170, 260))

        if connected:
            screen.blit(font_small.render(f"IP: {server_ip}:{server_port}", True, (140, 200, 140)), (280, 320))
            screen.blit(font.render("Хост ещё не начал игру...", True, (170, 188, 220)), (220, 380))
            screen.blit(font.render("Оставайтесь на связи!", True, (120, 220, 140)), (290, 430))

        if game_started:
            screen.blit(font_big.render("ИГРА НАЧИНАЕТСЯ!", True, (90, 220, 120)), (180, 280))
            pygame.display.flip()
            pygame.time.wait(800)
            pygame.quit()
            sock.close()

            # Запускаем основной игровой интерфейс
            env = os.environ.copy()
            env["INITIAL_GRID"] = "received"  # можно потом передавать реальную карту
            subprocess.Popen([sys.executable, os.path.join(BASE_DIR, "game_sandbox.py")], env=env)
            return

        pygame.display.flip()
        clock.tick(30)


if __name__ == "__main__":
    run_waiting_screen()