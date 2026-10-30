//! Storage format for `post.transcript_word_timestamps`.
//!
//! New values are gzip-compressed JSON stored as a BLOB. Rows written before
//! compression existed are plain JSON text, and the JSON text `null` marks a
//! cleared value; readers accept all three. Python mirrors this in
//! `app.models.CompressedJSON`.

use flate2::read::GzDecoder;
use flate2::write::GzEncoder;
use flate2::Compression;
use rusqlite::types::ValueRef;
use std::io::{Read, Write};

const GZIP_MAGIC: [u8; 2] = [0x1f, 0x8b];
// Level 6 compresses the word JSON about 7x at ~14 ms per hour-long episode.
const LEVEL: u32 = 6;
// Short values are not worth a compression header.
const MIN_COMPRESS_BYTES: usize = 1024;

/// Encode JSON text for storage: gzip BLOB when it is large enough, else text.
pub fn encode(json: &str) -> rusqlite::types::Value {
    if json.len() < MIN_COMPRESS_BYTES {
        return rusqlite::types::Value::Text(json.to_owned());
    }
    let mut encoder = GzEncoder::new(Vec::new(), Compression::new(LEVEL));
    // Writing to a Vec cannot fail.
    encoder.write_all(json.as_bytes()).expect("write to Vec");
    rusqlite::types::Value::Blob(encoder.finish().expect("finish gzip"))
}

/// Decode a stored value back to JSON text. Returns `None` for SQL NULL.
pub fn decode(value: ValueRef<'_>) -> rusqlite::Result<Option<String>> {
    match value {
        ValueRef::Null => Ok(None),
        ValueRef::Text(bytes) => Ok(Some(String::from_utf8_lossy(bytes).into_owned())),
        ValueRef::Blob(bytes) => decode_blob(bytes).map(Some),
        _ => Err(rusqlite::Error::InvalidColumnType(
            0,
            "transcript_word_timestamps".to_owned(),
            value.data_type(),
        )),
    }
}

fn decode_blob(bytes: &[u8]) -> rusqlite::Result<String> {
    let invalid = |message: &str| {
        rusqlite::Error::FromSqlConversionFailure(
            0,
            rusqlite::types::Type::Blob,
            message.to_owned().into(),
        )
    };
    if !bytes.starts_with(&GZIP_MAGIC) {
        return String::from_utf8(bytes.to_vec()).map_err(|_| invalid("not gzip or UTF-8"));
    }
    let mut out = String::new();
    GzDecoder::new(bytes)
        .read_to_string(&mut out)
        .map_err(|_| invalid("corrupt gzip data"))?;
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn round_trip(json: &str) -> String {
        let stored = encode(json);
        let value_ref = match &stored {
            rusqlite::types::Value::Text(text) => ValueRef::Text(text.as_bytes()),
            rusqlite::types::Value::Blob(bytes) => ValueRef::Blob(bytes),
            other => panic!("unexpected {other:?}"),
        };
        decode(value_ref).unwrap().unwrap()
    }

    #[test]
    fn large_json_is_compressed_and_round_trips() {
        let json = format!(
            "[{}]",
            r#"{"word":"hello","start":1.0,"end":1.5},"#.repeat(500)
        );
        let stored = encode(&json);
        assert!(matches!(&stored, rusqlite::types::Value::Blob(b) if b.len() < json.len() / 4));
        assert_eq!(round_trip(&json), json);
    }

    #[test]
    fn small_json_and_null_marker_stay_text() {
        assert!(matches!(encode("null"), rusqlite::types::Value::Text(_)));
        assert_eq!(round_trip("[]"), "[]");
    }

    #[test]
    fn plain_text_rows_and_sql_null_decode() {
        assert_eq!(
            decode(ValueRef::Text(br#"[{"a":1}]"#)).unwrap().as_deref(),
            Some(r#"[{"a":1}]"#)
        );
        assert_eq!(decode(ValueRef::Null).unwrap(), None);
    }

    #[test]
    fn corrupt_gzip_is_an_error() {
        let mut stored = match encode(&"x".repeat(4096)) {
            rusqlite::types::Value::Blob(bytes) => bytes,
            other => panic!("unexpected {other:?}"),
        };
        let middle = stored.len() / 2;
        stored[middle] ^= 0x02;
        assert!(decode(ValueRef::Blob(&stored)).is_err());
    }
}
