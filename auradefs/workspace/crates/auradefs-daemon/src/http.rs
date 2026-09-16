//! A small HTTP/1.1 server, enough for a local API and no more.
//!
//! Bringing in a web framework for this would mean an async runtime and a
//! hundred crates to serve a handful of routes to one page on the loopback
//! interface. What is here is a request parser with every length capped, a
//! response writer, and a thread per connection.
//!
//! Every cap exists because the other end is a browser page that can be made
//! to send anything. A request line, a header block and a body all have limits,
//! and exceeding one ends the connection rather than growing a buffer.

use std::collections::HashMap;
use std::io::{BufReader, Read, Write};
use std::net::TcpStream;
use std::time::Duration;

pub const MAX_REQUEST_LINE: usize = 8 * 1024;
pub const MAX_HEADERS: usize = 64;
pub const MAX_HEADER_BYTES: usize = 16 * 1024;
pub const MAX_BODY: usize = 16 * 1024 * 1024;
pub const IDLE_TIMEOUT: Duration = Duration::from_secs(30);

/// One parsed request.
#[derive(Debug, Clone)]
pub struct Request {
    pub method: String,
    pub path: String,
    pub query: HashMap<String, String>,
    pub headers: HashMap<String, String>,
    pub body: Vec<u8>,
    pub keep_alive: bool,
}

impl Request {
    pub fn header(&self, name: &str) -> Option<&str> {
        self.headers.get(&name.to_ascii_lowercase()).map(String::as_str)
    }

    pub fn param(&self, name: &str) -> Option<&str> {
        self.query.get(name).map(String::as_str)
    }
}

/// What went wrong before a handler was ever reached.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ParseError {
    /// The connection ended cleanly with nothing on it.
    Closed,
    TooLarge,
    Malformed,
    Unsupported,
}

/// Read one request. Returns `Closed` when the peer went away between
/// requests, which on a keep alive connection is the normal ending.
pub fn read_request(reader: &mut BufReader<TcpStream>) -> Result<Request, ParseError> {
    let mut line = String::new();
    let read = read_line(reader, &mut line, MAX_REQUEST_LINE)?;
    if read == 0 {
        return Err(ParseError::Closed);
    }
    let mut parts = line.trim_end().split(' ');
    let method = parts.next().unwrap_or("").to_string();
    let target = parts.next().unwrap_or("").to_string();
    let version = parts.next().unwrap_or("HTTP/1.1").to_string();
    if method.is_empty() || target.is_empty() {
        return Err(ParseError::Malformed);
    }

    let mut headers = HashMap::new();
    let mut header_bytes = 0;
    loop {
        let mut header = String::new();
        let n = read_line(reader, &mut header, MAX_REQUEST_LINE)?;
        if n == 0 {
            return Err(ParseError::Malformed);
        }
        let header = header.trim_end_matches(['\r', '\n']);
        if header.is_empty() {
            break;
        }
        header_bytes += header.len();
        if headers.len() >= MAX_HEADERS || header_bytes > MAX_HEADER_BYTES {
            return Err(ParseError::TooLarge);
        }
        let Some((name, value)) = header.split_once(':') else {
            return Err(ParseError::Malformed);
        };
        //: Lowercased on the way in, so every later lookup is a plain match
        //: rather than a case insensitive search.
        headers.insert(name.trim().to_ascii_lowercase(), value.trim().to_string());
    }

    //: No chunked bodies. The one client is a page using fetch with a string
    //: body, which always sets a length, and accepting chunked would mean a
    //: second parser with its own limits to get right.
    if headers
        .get("transfer-encoding")
        .map(|v| v.to_ascii_lowercase().contains("chunked"))
        .unwrap_or(false)
    {
        return Err(ParseError::Unsupported);
    }

    let length: usize = headers
        .get("content-length")
        .and_then(|v| v.parse().ok())
        .unwrap_or(0);
    if length > MAX_BODY {
        return Err(ParseError::TooLarge);
    }
    let mut body = vec![0u8; length];
    if length > 0 {
        reader.read_exact(&mut body).map_err(|_| ParseError::Malformed)?;
    }

    let (path, query) = split_target(&target);
    let keep_alive = match headers.get("connection").map(|v| v.to_ascii_lowercase()) {
        Some(v) if v.contains("close") => false,
        Some(v) if v.contains("keep-alive") => true,
        _ => version != "HTTP/1.0",
    };

    Ok(Request { method, path, query, headers, body, keep_alive })
}

/// Read a line, refusing one longer than the cap rather than buffering it.
fn read_line(
    reader: &mut BufReader<TcpStream>,
    out: &mut String,
    cap: usize,
) -> Result<usize, ParseError> {
    let mut raw = Vec::new();
    let mut total = 0;
    loop {
        let mut byte = [0u8; 1];
        match reader.read(&mut byte) {
            Ok(0) => break,
            Ok(_) => {
                total += 1;
                if total > cap {
                    return Err(ParseError::TooLarge);
                }
                raw.push(byte[0]);
                if byte[0] == b'\n' {
                    break;
                }
            }
            Err(_) => return Err(ParseError::Malformed),
        }
    }
    *out = String::from_utf8_lossy(&raw).into_owned();
    Ok(total)
}

/// Split `/api/list?path=/home&all=1` and undo the percent encoding.
pub fn split_target(target: &str) -> (String, HashMap<String, String>) {
    let (path, query) = match target.split_once('?') {
        Some((p, q)) => (p, q),
        None => (target, ""),
    };
    let mut params = HashMap::new();
    for pair in query.split('&').filter(|p| !p.is_empty()) {
        let (key, value) = match pair.split_once('=') {
            Some((k, v)) => (k, v),
            None => (pair, ""),
        };
        params.insert(percent_decode(key), percent_decode(value));
    }
    (percent_decode(path), params)
}

/// Percent decoding, with `+` meaning a space as a query string writes it.
pub fn percent_decode(value: &str) -> String {
    let bytes = value.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'%' if i + 2 < bytes.len() => {
                match u8::from_str_radix(&value[i + 1..i + 3], 16) {
                    Ok(byte) => {
                        out.push(byte);
                        i += 3;
                    }
                    //: Not an escape after all, so it is just a percent sign.
                    Err(_) => {
                        out.push(b'%');
                        i += 1;
                    }
                }
            }
            b'+' => {
                out.push(b' ');
                i += 1;
            }
            other => {
                out.push(other);
                i += 1;
            }
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// A response, ready to write.
pub struct Response {
    pub status: u16,
    pub content_type: String,
    pub body: Vec<u8>,
    /// Extra headers, already formatted as name and value.
    pub extra: Vec<(String, String)>,
}

impl Response {
    pub fn json(status: u16, value: &serde_json::Value) -> Response {
        Response {
            status,
            content_type: "application/json".into(),
            body: serde_json::to_vec(value).unwrap_or_else(|_| b"{}".to_vec()),
            extra: Vec::new(),
        }
    }

    pub fn bytes(status: u16, content_type: &str, body: Vec<u8>) -> Response {
        Response {
            status,
            content_type: content_type.into(),
            body,
            extra: Vec::new(),
        }
    }

    pub fn empty(status: u16) -> Response {
        Response {
            status,
            content_type: "text/plain".into(),
            body: Vec::new(),
            extra: Vec::new(),
        }
    }
}

pub fn reason(status: u16) -> &'static str {
    match status {
        200 => "OK",
        204 => "No Content",
        400 => "Bad Request",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        409 => "Conflict",
        413 => "Payload Too Large",
        500 => "Internal Server Error",
        501 => "Not Implemented",
        503 => "Service Unavailable",
        _ => "Unknown",
    }
}

/// Is this origin one that may read the answers?
///
/// The service listens on the loopback interface, which is often mistaken for
/// a security boundary. It is not: any page in the browser can send a request
/// to `http://127.0.0.1:8901`, and with a permissive CORS header it can read
/// the reply. That is a listing of the user's home directory handed to a web
/// site. So the allowed origins are named, and everything else gets a refusal
/// rather than an answer.
///
/// A request with no `Origin` header at all is not from a browser's cross site
/// path, and is allowed: that is curl, a test, and the desktop's own code.
pub fn origin_allowed(origin: Option<&str>) -> bool {
    let Some(origin) = origin else { return true };
    //: Everything below is an allowance, and anything that matches none of
    //: them is refused. That is what handles the opaque origin a sandboxed
    //: frame sends as the literal string "null", and the empty one: neither
    //: needs a case of its own, and a case of its own would be untestable
    //: because removing it would change nothing.
    //:
    //: The desktop's own surfaces.
    for prefix in ["chrome://", "chrome-untrusted://", "chrome-extension://", "file://"] {
        if origin.starts_with(prefix) {
            return true;
        }
    }
    //: And a page served from this machine, on any port.
    for prefix in [
        "http://127.0.0.1", "https://127.0.0.1",
        "http://localhost", "https://localhost",
        "http://[::1]", "https://[::1]",
    ] {
        if origin == prefix {
            return true;
        }
        if let Some(rest) = origin.strip_prefix(prefix) {
            //: Only a port may follow. `http://localhost.evil.example` starts
            //: with the same text and is a different machine entirely.
            if rest.starts_with(':') && rest[1..].chars().all(|c| c.is_ascii_digit()) {
                return true;
            }
        }
    }
    false
}

/// Write a response. `keep_alive` decides the Connection header, and a false
/// answer here is also the caller's signal to close.
///
/// `origin` is echoed back rather than answered with a star, so a browser only
/// lets through the origins [`origin_allowed`] has already accepted.
pub fn write_response(
    stream: &mut TcpStream,
    response: &Response,
    keep_alive: bool,
) -> std::io::Result<()> {
    write_response_for(stream, response, keep_alive, None)
}

pub fn write_response_for(
    stream: &mut TcpStream,
    response: &Response,
    keep_alive: bool,
    origin: Option<&str>,
) -> std::io::Result<()> {
    let mut head = format!(
        "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: {}\r\n",
        response.status,
        reason(response.status),
        response.content_type,
        response.body.len(),
        if keep_alive { "keep-alive" } else { "close" },
    );
    for (name, value) in &response.extra {
        head.push_str(&format!("{name}: {value}\r\n"));
    }
    //: The page is served from a different origin than this port, so it needs
    //: to be allowed to read the answer. Only the one origin that asked, and
    //: only one that was allowed through in the first place.
    if let Some(origin) = origin.filter(|o| origin_allowed(Some(o))) {
        head.push_str(&format!("Access-Control-Allow-Origin: {origin}\r\n"));
        head.push_str("Vary: Origin\r\n");
    }
    head.push_str("Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS\r\n");
    head.push_str("Access-Control-Allow-Headers: Content-Type\r\n");
    //: Nothing here is worth a browser or a proxy keeping.
    head.push_str("Cache-Control: no-store\r\n");
    head.push_str("\r\n");
    stream.write_all(head.as_bytes())?;
    stream.write_all(&response.body)?;
    stream.flush()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_target_splits_into_a_path_and_decoded_parameters() {
        let (path, query) = split_target("/api/list?path=%2Fhome%2Fcam%2Fa%20b&all=1");
        assert_eq!(path, "/api/list");
        assert_eq!(query.get("path").unwrap(), "/home/cam/a b");
        assert_eq!(query.get("all").unwrap(), "1");

        let (path, query) = split_target("/api/health");
        assert_eq!(path, "/api/health");
        assert!(query.is_empty());
    }

    #[test]
    fn a_parameter_with_no_value_is_still_a_parameter() {
        let (_, query) = split_target("/x?flag&other=2");
        assert_eq!(query.get("flag").unwrap(), "");
        assert_eq!(query.get("other").unwrap(), "2");
    }

    #[test]
    fn percent_decoding_handles_what_a_file_name_can_contain() {
        assert_eq!(percent_decode("a%20b"), "a b");
        assert_eq!(percent_decode("a+b"), "a b");
        assert_eq!(percent_decode("100%"), "100%", "a stray percent is not an escape");
        assert_eq!(percent_decode("%zz"), "%zz", "a bad escape stays as written");
        assert_eq!(percent_decode("%2F%2E%2E%2F"), "/../");
        assert_eq!(percent_decode("caf%C3%A9"), "café");
    }

    #[test]
    fn a_path_that_decodes_to_a_traversal_is_visible_as_one() {
        //: The parser's job is to decode faithfully. Refusing the result is the
        //: router's job, and it can only do it if what arrives here is the
        //: decoded form rather than the escaped one.
        let (path, _) = split_target("/api/%2E%2E/secret");
        assert_eq!(path, "/api/../secret");
    }

    #[test]
    fn only_this_machines_own_pages_may_read_the_answers() {
        //: Not a browser, or a same origin request.
        assert!(origin_allowed(None));
        assert!(origin_allowed(Some("chrome://file-manager")));
        assert!(origin_allowed(Some("chrome-untrusted://aurade")));
        assert!(origin_allowed(Some("file://")));
        assert!(origin_allowed(Some("http://127.0.0.1:8901")));
        assert!(origin_allowed(Some("http://localhost:3000")));
        assert!(origin_allowed(Some("http://[::1]:8080")));

        //: A web page. This is the case the check exists for: without it, any
        //: site could read a listing of the user's home directory.
        assert!(!origin_allowed(Some("https://example.com")));
        assert!(!origin_allowed(Some("http://evil.example")));
        //: And the near misses, each of which is a different machine.
        assert!(!origin_allowed(Some("http://localhost.evil.example")));
        assert!(!origin_allowed(Some("http://127.0.0.1.evil.example")));
        assert!(!origin_allowed(Some("https://127.0.0.1@evil.example")));
        //: An opaque origin is what a sandboxed frame on a hostile page sends.
        assert!(!origin_allowed(Some("null")));
        assert!(!origin_allowed(Some("")));
    }

    #[test]
    fn the_status_line_names_the_codes_this_service_returns() {
        for status in [200, 204, 400, 403, 404, 405, 409, 413, 500, 501, 503] {
            assert_ne!(reason(status), "Unknown", "{status} has no reason phrase");
        }
    }
}
