package answers

import (
	"crypto/rand"
	"crypto/sha512"
	"fmt"
	"strings"
)

// The alphabet crypt(3) encodes with.
const cryptAlphabet = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

// HashPassword makes a SHA-512 crypt(3) hash ($6$), the same kind the
// installer makes from a typed password with `openssl passwd -6`, so the
// installed system treats the two the same. Only the hash leaves this
// computer; the password itself is never written anywhere.
func HashPassword(password string) (string, error) {
	if password == "" {
		return "", fmt.Errorf("the password is empty")
	}
	raw := make([]byte, 16)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	salt := make([]byte, 16)
	for i, b := range raw {
		salt[i] = cryptAlphabet[int(b)%len(cryptAlphabet)]
	}
	return sha512Crypt([]byte(password), salt), nil
}

// sha512Crypt is Ulrich Drepper's SHA-crypt with the default 5000 rounds.
func sha512Crypt(key, salt []byte) string {
	if len(salt) > 16 {
		salt = salt[:16]
	}
	b := sha512.New()
	b.Write(key)
	b.Write(salt)
	b.Write(key)
	sumB := b.Sum(nil)

	a := sha512.New()
	a.Write(key)
	a.Write(salt)
	n := len(key)
	for ; n > 64; n -= 64 {
		a.Write(sumB)
	}
	a.Write(sumB[:n])
	for n = len(key); n > 0; n >>= 1 {
		if n&1 != 0 {
			a.Write(sumB)
		} else {
			a.Write(key)
		}
	}
	sumA := a.Sum(nil)

	dp := sha512.New()
	for i := 0; i < len(key); i++ {
		dp.Write(key)
	}
	sumDP := dp.Sum(nil)
	p := make([]byte, 0, len(key))
	for n = len(key); n > 64; n -= 64 {
		p = append(p, sumDP...)
	}
	p = append(p, sumDP[:n]...)

	ds := sha512.New()
	for i := 0; i < 16+int(sumA[0]); i++ {
		ds.Write(salt)
	}
	sumDS := ds.Sum(nil)
	s := make([]byte, 0, len(salt))
	for n = len(salt); n > 64; n -= 64 {
		s = append(s, sumDS...)
	}
	s = append(s, sumDS[:n]...)

	c := sumA
	for i := 0; i < 5000; i++ {
		h := sha512.New()
		if i&1 != 0 {
			h.Write(p)
		} else {
			h.Write(c)
		}
		if i%3 != 0 {
			h.Write(s)
		}
		if i%7 != 0 {
			h.Write(p)
		}
		if i&1 != 0 {
			h.Write(c)
		} else {
			h.Write(p)
		}
		c = h.Sum(nil)
	}

	var out strings.Builder
	out.WriteString("$6$")
	out.Write(salt)
	out.WriteByte('$')
	enc := func(b2, b1, b0 byte, n int) {
		w := uint(b2)<<16 | uint(b1)<<8 | uint(b0)
		for ; n > 0; n-- {
			out.WriteByte(cryptAlphabet[w&0x3f])
			w >>= 6
		}
	}
	order := [][3]int{
		{0, 21, 42}, {22, 43, 1}, {44, 2, 23}, {3, 24, 45}, {25, 46, 4}, {47, 5, 26}, {6, 27, 48},
		{28, 49, 7}, {50, 8, 29}, {9, 30, 51}, {31, 52, 10}, {53, 11, 32}, {12, 33, 54}, {34, 55, 13},
		{56, 14, 35}, {15, 36, 57}, {37, 58, 16}, {59, 17, 38}, {18, 39, 60}, {40, 61, 19}, {62, 20, 41},
	}
	for _, o := range order {
		enc(c[o[0]], c[o[1]], c[o[2]], 4)
	}
	enc(0, 0, c[63], 2)
	return out.String()
}
