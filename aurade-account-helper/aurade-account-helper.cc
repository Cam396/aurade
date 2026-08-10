// Copyright 2026 AuraDE Contributors
// SPDX-License-Identifier: BSD-3-Clause

#include <pwd.h>
#include <security/pam_appl.h>
#include <sys/types.h>
#include <unistd.h>

#include <cctype>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

namespace {

struct PamSecrets {
  std::string current_password;
  std::string new_password;
};

std::string JsonEscape(const std::string& value) {
  std::ostringstream out;
  for (const char c : value) {
    switch (c) {
      case '\\':
        out << "\\\\";
        break;
      case '"':
        out << "\\\"";
        break;
      case '\n':
        out << "\\n";
        break;
      case '\r':
        out << "\\r";
        break;
      case '\t':
        out << "\\t";
        break;
      default:
        out << c;
    }
  }
  return out.str();
}

[[noreturn]] void Die(const std::string& message, int exit_code = 1) {
  std::cerr << "aurade-account-helper: " << message << '\n';
  std::exit(exit_code);
}

std::string ReadSecretLine(const char* label) {
  std::string line;
  if (!std::getline(std::cin, line)) {
    Die(std::string("missing stdin secret: ") + label, 2);
  }
  return line;
}

std::string CurrentUsername() {
  passwd* pw = getpwuid(getuid());
  if (!pw || !pw->pw_name) {
    Die("cannot resolve current user");
  }
  return pw->pw_name;
}

passwd* ResolveUser(const std::string& username) {
  passwd* pw = getpwnam(username.c_str());
  if (!pw) {
    Die("user does not exist: " + username);
  }
  return pw;
}

void RequireAllowedTargetUser(const std::string& username) {
  if (geteuid() == 0) {
    return;
  }
  if (username != CurrentUsername()) {
    Die("non-root callers may only operate on the current user");
  }
}

std::optional<std::string> ArgValue(const std::vector<std::string>& args,
                                    const std::string& name) {
  for (size_t i = 0; i + 1 < args.size(); ++i) {
    if (args[i] == name) {
      return args[i + 1];
    }
  }
  return std::nullopt;
}

int PamConversation(int num_msg,
                    const pam_message** msg,
                    pam_response** resp,
                    void* appdata_ptr) {
  if (num_msg <= 0) {
    return PAM_CONV_ERR;
  }

  PamSecrets* secrets = static_cast<PamSecrets*>(appdata_ptr);
  pam_response* responses =
      static_cast<pam_response*>(calloc(num_msg, sizeof(pam_response)));
  if (!responses) {
    return PAM_BUF_ERR;
  }

  for (int i = 0; i < num_msg; ++i) {
    const int style = msg[i]->msg_style;
    if (style != PAM_PROMPT_ECHO_OFF && style != PAM_PROMPT_ECHO_ON) {
      continue;
    }

    std::string prompt = msg[i]->msg ? msg[i]->msg : "";
    for (char& c : prompt) {
      c = static_cast<char>(std::tolower(c));
    }

    const bool wants_new =
        prompt.find("new") != std::string::npos ||
        prompt.find("retype") != std::string::npos ||
        prompt.find("again") != std::string::npos;
    const std::string& value =
        wants_new && !secrets->new_password.empty()
            ? secrets->new_password
            : secrets->current_password;
    responses[i].resp = strdup(value.c_str());
    if (!responses[i].resp) {
      for (int j = 0; j < i; ++j) {
        free(responses[j].resp);
      }
      free(responses);
      return PAM_BUF_ERR;
    }
  }

  *resp = responses;
  return PAM_SUCCESS;
}

void CheckPamResult(pam_handle_t* pamh, int result, const std::string& action) {
  if (result != PAM_SUCCESS) {
    std::string message = action + " failed";
    if (pamh) {
      message += ": ";
      message += pam_strerror(pamh, result);
    }
    Die(message);
  }
}

void CurrentUserJson() {
  passwd* pw = getpwuid(getuid());
  if (!pw) {
    Die("cannot resolve current user");
  }

  std::cout << "{"
            << "\"username\":\"" << JsonEscape(pw->pw_name ? pw->pw_name : "")
            << "\",\"uid\":" << static_cast<unsigned long>(pw->pw_uid)
            << ",\"gid\":" << static_cast<unsigned long>(pw->pw_gid)
            << ",\"home\":\"" << JsonEscape(pw->pw_dir ? pw->pw_dir : "")
            << "\",\"shell\":\"" << JsonEscape(pw->pw_shell ? pw->pw_shell : "")
            << "\",\"gecos\":\"" << JsonEscape(pw->pw_gecos ? pw->pw_gecos : "")
            << "\"}\n";
}

void VerifyPassword(const std::string& username) {
  ResolveUser(username);
  RequireAllowedTargetUser(username);

  PamSecrets secrets;
  secrets.current_password = ReadSecretLine("current-password");

  pam_conv conv = {PamConversation, &secrets};
  pam_handle_t* pamh = nullptr;
  int result = pam_start("aurade", username.c_str(), &conv, &pamh);
  CheckPamResult(pamh, result, "pam_start");
  result = pam_authenticate(pamh, 0);
  CheckPamResult(pamh, result, "authentication");
  result = pam_acct_mgmt(pamh, 0);
  CheckPamResult(pamh, result, "account validation");
  pam_end(pamh, PAM_SUCCESS);
}

void ChangePassword(const std::string& username) {
  ResolveUser(username);
  RequireAllowedTargetUser(username);

  PamSecrets secrets;
  secrets.current_password = ReadSecretLine("current-password");
  secrets.new_password = ReadSecretLine("new-password");
  if (secrets.new_password.empty()) {
    Die("new password cannot be empty", 2);
  }

  pam_conv conv = {PamConversation, &secrets};
  pam_handle_t* pamh = nullptr;
  int result = pam_start("aurade", username.c_str(), &conv, &pamh);
  CheckPamResult(pamh, result, "pam_start");
  result = pam_authenticate(pamh, 0);
  CheckPamResult(pamh, result, "authentication");
  result = pam_chauthtok(pamh, 0);
  CheckPamResult(pamh, result, "password change");
  pam_end(pamh, PAM_SUCCESS);
}

void Usage() {
  std::cerr
      << "Usage:\n"
      << "  aurade-account-helper current-user --json\n"
      << "  aurade-account-helper verify-password --user <name> < stdin\n"
      << "  aurade-account-helper change-password --user <name> < stdin\n";
}

}  // namespace

int main(int argc, char** argv) {
  std::vector<std::string> args(argv + 1, argv + argc);
  if (args.empty()) {
    Usage();
    return 2;
  }

  const std::string command = args[0];
  if (command == "current-user") {
    if (args.size() != 2 || args[1] != "--json") {
      Usage();
      return 2;
    }
    CurrentUserJson();
    return 0;
  }

  std::optional<std::string> username = ArgValue(args, "--user");
  if (!username || username->empty()) {
    Usage();
    return 2;
  }

  if (command == "verify-password") {
    VerifyPassword(*username);
    return 0;
  }
  if (command == "change-password") {
    ChangePassword(*username);
    return 0;
  }

  Usage();
  return 2;
}
