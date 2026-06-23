#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/sendfile.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define PORT 80
#define ROOT "/site"
#define BUF_SIZE 4096

static const char *mime_type(const char *path) {
  const char *ext = strrchr(path, '.');
  if (!ext) return "application/octet-stream";
  if (strcmp(ext, ".html") == 0) return "text/html; charset=utf-8";
  if (strcmp(ext, ".css") == 0) return "text/css; charset=utf-8";
  if (strcmp(ext, ".js") == 0) return "application/javascript; charset=utf-8";
  if (strcmp(ext, ".json") == 0) return "application/json; charset=utf-8";
  if (strcmp(ext, ".txt") == 0) return "text/plain; charset=utf-8";
  return "application/octet-stream";
}

static void send_text(int client, int status, const char *label, const char *body) {
  char header[512];
  int body_len = (int)strlen(body);
  int n = snprintf(header, sizeof(header),
                   "HTTP/1.1 %d %s\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: %d\r\nConnection: close\r\n\r\n",
                   status, label, body_len);
  send(client, header, n, 0);
  send(client, body, body_len, 0);
}

static void handle_client(int client) {
  char buffer[BUF_SIZE];
  ssize_t received = recv(client, buffer, sizeof(buffer) - 1, 0);
  if (received <= 0) return;
  buffer[received] = '\0';

  char method[16] = {0};
  char url[1024] = {0};
  if (sscanf(buffer, "%15s %1023s", method, url) != 2) {
    send_text(client, 400, "Bad Request", "Bad Request\n");
    return;
  }

  if (strcmp(method, "GET") != 0 && strcmp(method, "HEAD") != 0) {
    send_text(client, 405, "Method Not Allowed", "Method Not Allowed\n");
    return;
  }

  char *query = strchr(url, '?');
  if (query) *query = '\0';
  if (strstr(url, "..")) {
    send_text(client, 403, "Forbidden", "Forbidden\n");
    return;
  }

  char path[1400];
  if (strcmp(url, "/") == 0) {
    snprintf(path, sizeof(path), "%s/index.html", ROOT);
  } else {
    snprintf(path, sizeof(path), "%s%s", ROOT, url);
  }

  int fd = open(path, O_RDONLY);
  if (fd < 0) {
    send_text(client, 404, "Not Found", "Not Found\n");
    return;
  }

  struct stat st;
  if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode)) {
    close(fd);
    send_text(client, 404, "Not Found", "Not Found\n");
    return;
  }

  char header[512];
  int n = snprintf(header, sizeof(header),
                   "HTTP/1.1 200 OK\r\nContent-Type: %s\r\nContent-Length: %lld\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n",
                   mime_type(path), (long long)st.st_size);
  send(client, header, n, 0);

  if (strcmp(method, "HEAD") != 0) {
    off_t offset = 0;
    while (offset < st.st_size) {
      ssize_t sent = sendfile(client, fd, &offset, st.st_size - offset);
      if (sent <= 0) break;
    }
  }
  close(fd);
}

int main(void) {
  signal(SIGPIPE, SIG_IGN);

  int server = socket(AF_INET, SOCK_STREAM, 0);
  if (server < 0) {
    perror("socket");
    return 1;
  }

  int opt = 1;
  setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

  struct sockaddr_in addr;
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons(PORT);

  if (bind(server, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
    perror("bind");
    return 1;
  }

  if (listen(server, 64) < 0) {
    perror("listen");
    return 1;
  }

  printf("Agent Mission Control static server listening on port %d\n", PORT);
  fflush(stdout);

  while (1) {
    int client = accept(server, NULL, NULL);
    if (client < 0) {
      if (errno == EINTR) continue;
      perror("accept");
      continue;
    }
    handle_client(client);
    close(client);
  }
}
