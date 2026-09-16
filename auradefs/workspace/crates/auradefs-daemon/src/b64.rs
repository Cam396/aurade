//! Base64, for the data URIs the page uses.
//!
//! Twenty lines and a test against the published vectors, rather than a
//! dependency. A thumbnail arrives inline in the JSON because the page draws
//! it immediately and a second request per row would be a second request per
//! row.

const ALPHABET: &[u8; 64] =
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/// Standard base64 with padding.
pub fn encode(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let b = [
            chunk[0],
            *chunk.get(1).unwrap_or(&0),
            *chunk.get(2).unwrap_or(&0),
        ];
        let n = ((b[0] as u32) << 16) | ((b[1] as u32) << 8) | b[2] as u32;
        out.push(ALPHABET[(n >> 18) as usize & 63] as char);
        out.push(ALPHABET[(n >> 12) as usize & 63] as char);
        //: The padding is what says how many of the last three bytes were
        //: real, and a decoder that is handed the wrong count returns the
        //: wrong image.
        out.push(if chunk.len() > 1 { ALPHABET[(n >> 6) as usize & 63] as char } else { '=' });
        out.push(if chunk.len() > 2 { ALPHABET[n as usize & 63] as char } else { '=' });
    }
    out
}

/// A `data:` URI ready to put in an `src`.
pub fn data_uri(mime: &str, bytes: &[u8]) -> String {
    format!("data:{mime};base64,{}", encode(bytes))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_published_vectors_come_out_right() {
        //: RFC 4648 section 10, which is where every implementation gets
        //: checked, including the padding cases that are easy to get wrong.
        assert_eq!(encode(b""), "");
        assert_eq!(encode(b"f"), "Zg==");
        assert_eq!(encode(b"fo"), "Zm8=");
        assert_eq!(encode(b"foo"), "Zm9v");
        assert_eq!(encode(b"foob"), "Zm9vYg==");
        assert_eq!(encode(b"fooba"), "Zm9vYmE=");
        assert_eq!(encode(b"foobar"), "Zm9vYmFy");
    }

    #[test]
    fn the_high_bytes_a_png_is_full_of_survive() {
        assert_eq!(encode(&[0xff, 0xfe, 0xfd]), "//79");
        assert_eq!(encode(&[0x89, b'P', b'N', b'G']), "iVBORw==");
        assert_eq!(encode(&[0x00]), "AA==");
    }

    #[test]
    fn a_data_uri_is_the_shape_an_src_takes() {
        assert_eq!(data_uri("image/png", b"foo"), "data:image/png;base64,Zm9v");
    }

    #[test]
    fn the_length_is_always_a_multiple_of_four() {
        for n in 0..40 {
            let encoded = encode(&vec![b'x'; n]);
            assert_eq!(encoded.len() % 4, 0, "{n} bytes gave {} characters", encoded.len());
            assert_eq!(encoded.len(), n.div_ceil(3) * 4);
        }
    }
}
