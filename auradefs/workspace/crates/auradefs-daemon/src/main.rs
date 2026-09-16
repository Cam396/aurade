//! The AuraDE file service.
//!
//! One process, one library, two ways in. Today it answers HTTP on the loopback
//! interface, which is what the prototype page speaks. The D-Bus interface that
//! the shipped desktop will use is the same [`api`] module behind a different
//! transport, which is the reason none of the decisions live in the transport.
//!
//! It refuses to listen anywhere but the loopback interface. A file service
//! bound to a real interface is a way to read someone's home directory from the
//! next desk, and no option is offered to do it.

mod api;
mod b64;
mod http;
mod jobs;

use std::io::BufReader;
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

use http::{ParseError, Response};

const DEFAULT_PORT: u16 = 8901;
/// Enough for a page that opens a handful of parallel requests, low enough that
/// a runaway client cannot make this process the reason the machine is out of
/// threads.
const MAX_CONNECTIONS: usize = 64;

fn main() {
    let mut port = DEFAULT_PORT;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--port" => {
                port = args
                    .next()
                    .and_then(|v| v.parse().ok())
                    .unwrap_or_else(|| fail("--port needs a number"));
            }
            "--help" | "-h" => {
                println!("auradefs [--port N]");
                println!("The AuraDE file service. Listens on 127.0.0.1 only.");
                return;
            }
            other => fail(&format!("unknown option {other}")),
        }
    }

    let address = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), port);
    let listener = match TcpListener::bind(address) {
        Ok(l) => l,
        Err(e) => fail(&format!("cannot listen on {address}: {e}")),
    };
    //: Belt and braces. The address above is a constant, but a later edit that
    //: made it configurable would otherwise be a one line change away from
    //: serving the network.
    match listener.local_addr() {
        Ok(bound) if bound.ip().is_loopback() => {}
        Ok(bound) => fail(&format!("refusing to serve on {bound}")),
        Err(e) => fail(&format!("cannot read the bound address: {e}")),
    }

    let service = Arc::new(api::Service::new());
    let live = Arc::new(AtomicUsize::new(0));
    println!("auradefs on http://{address} (loopback only)");

    for incoming in listener.incoming() {
        let stream = match incoming {
            Ok(s) => s,
            //: One failed accept is not a reason to stop answering.
            Err(_) => continue,
        };
        if live.load(Ordering::Relaxed) >= MAX_CONNECTIONS {
            let mut stream = stream;
            let _ = http::write_response(&mut stream, &busy(), false);
            continue;
        }
        live.fetch_add(1, Ordering::Relaxed);
        let service = Arc::clone(&service);
        let live_now = Arc::clone(&live);
        let spawned = std::thread::Builder::new()
            .name("connection".into())
            .spawn(move || {
                serve(stream, &service);
                live_now.fetch_sub(1, Ordering::Relaxed);
            });
        if spawned.is_err() {
            live.fetch_sub(1, Ordering::Relaxed);
        }
    }
}

fn busy() -> Response {
    Response::json(
        503,
        &serde_json::json!({
            "error": "too many connections",
            "code": "busy",
            "errno": 11,
        }),
    )
}

/// One connection, until the client goes away or asks to close.
fn serve(stream: TcpStream, service: &Arc<api::Service>) {
    let _ = stream.set_read_timeout(Some(http::IDLE_TIMEOUT));
    let _ = stream.set_write_timeout(Some(http::IDLE_TIMEOUT));
    let _ = stream.set_nodelay(true);
    let Ok(mut writer) = stream.try_clone() else { return };
    let mut reader = BufReader::new(stream);

    loop {
        let request = match http::read_request(&mut reader) {
            Ok(r) => r,
            Err(ParseError::Closed) => return,
            Err(other) => {
                let status = match other {
                    ParseError::TooLarge => 413,
                    ParseError::Unsupported => 501,
                    _ => 400,
                };
                let response = Response::json(
                    status,
                    &serde_json::json!({
                        "error": format!("{other:?}").to_lowercase(),
                        "code": "bad-request",
                    }),
                );
                let _ = http::write_response(&mut writer, &response, false);
                return;
            }
        };
        let keep_alive = request.keep_alive;
        let origin = request.header("origin").map(str::to_string);
        let response = if http::origin_allowed(origin.as_deref()) {
            api::route(service, &request)
        } else {
            //: No CORS header goes back with this, so the page cannot read it
            //: either way. The status is for the person reading the log.
            Response::json(
                403,
                &serde_json::json!({
                    "error": "this origin may not use the file service",
                    "code": "denied",
                }),
            )
        };
        if http::write_response_for(&mut writer, &response, keep_alive, origin.as_deref()).is_err()
            || !keep_alive
        {
            return;
        }
    }
}

fn fail(message: &str) -> ! {
    eprintln!("auradefs: {message}");
    std::process::exit(2);
}
