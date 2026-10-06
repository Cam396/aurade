// Checks whether the password on standard input is the password of the user
// running this program, through PAM, and answers with the exit status: 0 when
// it is, 1 when it is not, 2 when it cannot tell.
//
// The desktop's lock screen runs it to unlock. The password comes on standard
// input so that it is never in a command line, and the user is the one this
// process runs as, never one the caller names, so it cannot be used to try
// passwords against another account. It authenticates the way gtklock and
// swaylock do, with the "aurade-lock" PAM service, which includes "login",
// and PAM's own delay after a wrong password applies here as well.

#define _GNU_SOURCE
#include <pwd.h>
#include <security/pam_appl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MAX_PASSWORD 4096

static char password[MAX_PASSWORD + 1];

static int answer(int count,
                  const struct pam_message **messages,
                  struct pam_response **responses,
                  void *data) {
  (void)data;
  if (count <= 0 || count > PAM_MAX_NUM_MSG) {
    return PAM_CONV_ERR;
  }
  struct pam_response *replies = calloc((size_t)count, sizeof(*replies));
  if (!replies) {
    return PAM_BUF_ERR;
  }
  for (int i = 0; i < count; ++i) {
    switch (messages[i]->msg_style) {
      case PAM_PROMPT_ECHO_OFF:
      case PAM_PROMPT_ECHO_ON:
        replies[i].resp = strdup(password);
        if (!replies[i].resp) {
          for (int j = 0; j < i; ++j) {
            if (replies[j].resp) {
              explicit_bzero(replies[j].resp, strlen(replies[j].resp));
              free(replies[j].resp);
            }
          }
          free(replies);
          return PAM_BUF_ERR;
        }
        break;
      default:
        // Information and errors are for a person at a terminal; the lock
        // screen says what went wrong itself.
        break;
    }
  }
  *responses = replies;
  return PAM_SUCCESS;
}

int main(void) {
  size_t length = 0;
  while (length < MAX_PASSWORD) {
    ssize_t got = read(STDIN_FILENO, password + length, MAX_PASSWORD - length);
    if (got < 0) {
      explicit_bzero(password, sizeof(password));
      return 2;
    }
    if (got == 0) {
      break;
    }
    length += (size_t)got;
  }
  password[length] = '\0';
  if (length == 0 || strlen(password) != length) {
    explicit_bzero(password, sizeof(password));
    return 1;
  }

  struct passwd *user = getpwuid(getuid());
  if (!user || !user->pw_name) {
    explicit_bzero(password, sizeof(password));
    return 2;
  }

  const struct pam_conv conversation = {answer, NULL};
  pam_handle_t *handle = NULL;
  int result = pam_start("aurade-lock", user->pw_name, &conversation, &handle);
  if (result == PAM_SUCCESS) {
    result = pam_authenticate(handle, 0);
  }
  if (handle) {
    pam_end(handle, result);
  }
  explicit_bzero(password, sizeof(password));
  return result == PAM_SUCCESS ? 0 : 1;
}
