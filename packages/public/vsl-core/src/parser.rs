//! VSL Parser — BNF grammar for Viable System Language
//!
//! Parses VSL expressions from the formal specification:
//! - VSM structure: ⟨S1, S2, S3, S4, S5⟩ @ E(L)
//! - Trust: trust(t+1) = (1-λ)*decay(trust(t), λ) + λ*observation(t)
//! - Channels: φ↑, φ↓, ψ, S3*, α, σ
//! - Axioms: ∀ x ∈ X: P(x)
//!
//! Grammar (simplified BNF):
//!   vsm       ::= "⟨" subsystems "⟩" "@" level
//!   subsystems ::= subsystem ("," subsystem)*
//!   subsystem  ::= "S" digit
//!   level      ::= "E(" digit ")"
//!   channel    ::= "φ↑" | "φ↓" | "ψ" | "S3*" | "α" | "σ"
//!   axiom      ::= "∀" var "∈" set ":" expr
//!   trust_expr ::= "trust" "(" expr ")" "=" expr
//!   expr       ::= term (("+" | "-") term)*
//!   term       ::= factor (("*" | "/") factor)*
//!   factor     ::= number | var | "(" expr ")"

use thiserror::Error;

// ─── TOKENS ──────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq)]
pub enum Token {
    // Structural
    Langle,         // ⟨
    Rangle,         // ⟩
    At,             // @
    LParen,         // (
    RParen,         // )
    LBrace,         // {
    RBrace,         // }
    Comma,
    Colon,
    Semicolon,

    // VSM
    Subsystem(u8),  // S1, S2, ..., S5
    Level(u32),     // E(0), E(1), ...

    // Channels
    PhiUp,          // φ↑
    PhiDown,        // φ↓
    Psi,            // ψ
    S3Star,         // S3*
    Alpha,          // α
    Sigma,          // σ

    // Logic
    Forall,         // ∀
    Exists,         // ∃
    In,             // ∈
    Implies,        // ⟹
    Equivalent,     // ⟺

    // Arithmetic
    Plus,
    Minus,
    Star,
    Slash,
    Equals,

    // Atoms
    Ident(String),
    Number(f64),

    // Keywords
    Trust,
    Decay,
    Observation,
    Vsm,
    Eof,
}

// ─── ERRORS ──────────────────────────────────────────────────────

#[derive(Error, Debug, Clone, PartialEq)]
pub enum ParseError {
    #[error("unexpected token: expected {expected}, got {got}")]
    UnexpectedToken { expected: String, got: String },

    #[error("unexpected end of input")]
    UnexpectedEof,

    #[error("invalid number: {0}")]
    InvalidNumber(String),

    #[error("unknown channel: {0}")]
    UnknownChannel(String),

    #[error("invalid subsystem: {0}")]
    InvalidSubsystem(String),
}

pub type ParseResult<T> = Result<T, ParseError>;

// ─── AST ─────────────────────────────────────────────────────────

/// A VSM declaration: ⟨S1, S2, S3, S4, S5⟩ @ E(L)
#[derive(Debug, Clone, PartialEq)]
pub struct VsmDecl {
    pub subsystems: Vec<u8>,  // [1, 2, 3, 4, 5]
    pub level: u32,
}

/// Channel types
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChannelType {
    PhiUp,
    PhiDown,
    Psi,
    S3Star,
    Alpha,
    Sigma,
}

impl ChannelType {
    pub fn symbol(&self) -> &'static str {
        match self {
            Self::PhiUp => "φ↑",
            Self::PhiDown => "φ↓",
            Self::Psi => "ψ",
            Self::S3Star => "S3*",
            Self::Alpha => "α",
            Self::Sigma => "σ",
        }
    }
}

/// An axiom: ∀ x ∈ Set: Expression
#[derive(Debug, Clone, PartialEq)]
pub struct AxiomDecl {
    pub var: String,
    pub set: String,
    pub expr: Expr,
}

/// Expressions in VSL
#[derive(Debug, Clone, PartialEq)]
pub enum Expr {
    Number(f64),
    Ident(String),
    BinaryOp {
        op: BinOp,
        left: Box<Expr>,
        right: Box<Expr>,
    },
    FunctionCall {
        name: String,
        args: Vec<Expr>,
    },
    TrustExpr {
        time: Box<Expr>,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BinOp {
    Add,
    Sub,
    Mul,
    Div,
    Eq,
}

/// Top-level VSL declarations
#[derive(Debug, Clone, PartialEq)]
pub enum Decl {
    Vsm(VsmDecl),
    Axiom(AxiomDecl),
    Trust {
        time: Expr,
        expr: Expr,
    },
}

// ─── LEXER ───────────────────────────────────────────────────────

pub struct Lexer {
    chars: Vec<char>,
    pos: usize,
}

impl Lexer {
    pub fn new(input: &str) -> Self {
        Self {
            chars: input.chars().collect(),
            pos: 0,
        }
    }

    fn peek(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }

    fn advance(&mut self) -> Option<char> {
        let ch = self.chars.get(self.pos).copied();
        if ch.is_some() {
            self.pos += 1;
        }
        ch
    }

    fn skip_whitespace(&mut self) {
        while let Some(ch) = self.peek() {
            if ch.is_whitespace() {
                self.advance();
            } else {
                break;
            }
        }
    }

    fn read_number(&mut self) -> ParseResult<Token> {
        let mut s = String::new();
        while let Some(ch) = self.peek() {
            if ch.is_ascii_digit() || ch == '.' {
                s.push(ch);
                self.advance();
            } else {
                break;
            }
        }
        let n: f64 = s.parse().map_err(|_| ParseError::InvalidNumber(s.clone()))?;
        Ok(Token::Number(n))
    }

    fn read_ident(&mut self) -> Token {
        let mut s = String::new();
        while let Some(ch) = self.peek() {
            if ch.is_alphanumeric() || ch == '_' {
                s.push(ch);
                self.advance();
            } else {
                break;
            }
        }
        match s.as_str() {
            "trust" => Token::Trust,
            "decay" => Token::Decay,
            "observation" => Token::Observation,
            "V" => Token::Vsm,
            _ => Token::Ident(s),
        }
    }

    pub fn tokenize(&mut self) -> ParseResult<Vec<Token>> {
        let mut tokens = Vec::new();
        loop {
            self.skip_whitespace();
            let ch = match self.peek() {
                Some(c) => c,
                None => {
                    tokens.push(Token::Eof);
                    break;
                }
            };

            let tok = match ch {
                '⟨' => { self.advance(); Token::Langle }
                '⟩' => { self.advance(); Token::Rangle }
                '@' => { self.advance(); Token::At }
                '(' => { self.advance(); Token::LParen }
                ')' => { self.advance(); Token::RParen }
                '{' => { self.advance(); Token::LBrace }
                '}' => { self.advance(); Token::RBrace }
                ',' => { self.advance(); Token::Comma }
                ':' => { self.advance(); Token::Colon }
                ';' => { self.advance(); Token::Semicolon }
                '+' => { self.advance(); Token::Plus }
                '-' => { self.advance(); Token::Minus }
                '*' => { self.advance(); Token::Star }
                '/' => { self.advance(); Token::Slash }
                '=' => { self.advance(); Token::Equals }
                '∀' => { self.advance(); Token::Forall }
                '∃' => { self.advance(); Token::Exists }
                '∈' => { self.advance(); Token::In }
                '⟹' => { self.advance(); Token::Implies }
                '⟺' => { self.advance(); Token::Equivalent }
                'φ' => {
                    self.advance();
                    if self.peek() == Some('↑') {
                        self.advance();
                        Token::PhiUp
                    } else if self.peek() == Some('↓') {
                        self.advance();
                        Token::PhiDown
                    } else {
                        Token::Ident("φ".to_string())
                    }
                }
                'ψ' => { self.advance(); Token::Psi }
                'α' => { self.advance(); Token::Alpha }
                'σ' => { self.advance(); Token::Sigma }
                'S' => {
                    self.advance();
                    if self.peek() == Some('3') && self.peek_ahead(1) == Some('*') {
                        self.advance();
                        self.advance();
                        Token::S3Star
                    } else if let Some(d @ '1'..='5') = self.peek() {
                        self.advance();
                        Token::Subsystem(d as u8 - b'0')
                    } else {
                        Token::Ident("S".to_string())
                    }
                }
                'E' if self.peek_ahead(1) == Some('(') => {
                    self.advance(); // E
                    self.advance(); // (
                    let mut num = String::new();
                    while let Some(c) = self.peek() {
                        if c.is_ascii_digit() {
                            num.push(c);
                            self.advance();
                        } else {
                            break;
                        }
                    }
                    if self.peek() == Some(')') {
                        self.advance();
                    }
                    let n: u32 = num.parse().unwrap_or(0);
                    Token::Level(n)
                }
                c if c.is_ascii_digit() => self.read_number()?,
                c if c.is_alphabetic() => self.read_ident(),
                _ => {
                    self.advance();
                    continue; // skip unknown chars
                }
            };
            tokens.push(tok);
        }
        Ok(tokens)
    }

    fn peek_ahead(&self, offset: usize) -> Option<char> {
        self.chars.get(self.pos + offset).copied()
    }
}

// ─── PARSER ──────────────────────────────────────────────────────

pub struct Parser {
    tokens: Vec<Token>,
    pos: usize,
}

impl Parser {
    pub fn new(tokens: Vec<Token>) -> Self {
        Self { tokens, pos: 0 }
    }

    fn peek(&self) -> &Token {
        self.tokens.get(self.pos).unwrap_or(&Token::Eof)
    }

    fn advance(&mut self) -> Token {
        let tok = self.tokens.get(self.pos).cloned().unwrap_or(Token::Eof);
        self.pos += 1;
        tok
    }

    fn expect(&mut self, expected: &Token) -> ParseResult<()> {
        let tok = self.advance();
        if &tok == expected {
            Ok(())
        } else {
            Err(ParseError::UnexpectedToken {
                expected: format!("{expected:?}"),
                got: format!("{tok:?}"),
            })
        }
    }

    /// Parse a top-level declaration
    pub fn parse_decl(&mut self) -> ParseResult<Decl> {
        // Skip semicolons between declarations
        while self.peek() == &Token::Semicolon {
            self.advance();
        }
        match self.peek().clone() {
            Token::Langle => Ok(Decl::Vsm(self.parse_vsm_decl()?)),
            Token::Forall => Ok(Decl::Axiom(self.parse_axiom_decl()?)),
            Token::Trust => {
                self.advance(); // trust
                self.expect(&Token::LParen)?;
                let time = self.parse_expr()?;
                self.expect(&Token::RParen)?;
                self.expect(&Token::Equals)?;
                let expr = self.parse_expr()?;
                Ok(Decl::Trust { time, expr })
            }
            tok => Err(ParseError::UnexpectedToken {
                expected: "⟨, ∀, or trust".to_string(),
                got: format!("{tok:?}"),
            }),
        }
    }

    /// Parse VSM: ⟨S1, S2, S3, S4, S5⟩ @ E(L)
    fn parse_vsm_decl(&mut self) -> ParseResult<VsmDecl> {
        self.expect(&Token::Langle)?;
        let mut subsystems = Vec::new();
        loop {
            match self.advance() {
                Token::Subsystem(n) => subsystems.push(n),
                Token::Rangle => break,
                tok => {
                    return Err(ParseError::UnexpectedToken {
                        expected: "S1-S5 or ⟩".to_string(),
                        got: format!("{tok:?}"),
                    });
                }
            }
            if self.peek() == &Token::Comma {
                self.advance();
            }
        }
        self.expect(&Token::At)?;
        let level = match self.advance() {
            Token::Level(n) => n,
            tok => {
                return Err(ParseError::UnexpectedToken {
                    expected: "E(L)".to_string(),
                    got: format!("{tok:?}"),
                });
            }
        };
        Ok(VsmDecl { subsystems, level })
    }

    /// Parse axiom: ∀ x ∈ Set: expr
    fn parse_axiom_decl(&mut self) -> ParseResult<AxiomDecl> {
        self.expect(&Token::Forall)?;
        let var = match self.advance() {
            Token::Ident(s) => s,
            tok => {
                return Err(ParseError::UnexpectedToken {
                    expected: "identifier".to_string(),
                    got: format!("{tok:?}"),
                });
            }
        };
        self.expect(&Token::In)?;
        let set = match self.advance() {
            Token::Ident(s) => s,
            tok => {
                return Err(ParseError::UnexpectedToken {
                    expected: "set name".to_string(),
                    got: format!("{tok:?}"),
                });
            }
        };
        self.expect(&Token::Colon)?;
        let expr = self.parse_expr()?;
        Ok(AxiomDecl { var, set, expr })
    }

    /// Parse expression: term ((+|-) term)*
    fn parse_expr(&mut self) -> ParseResult<Expr> {
        let mut left = self.parse_term()?;
        loop {
            match self.peek() {
                Token::Plus => {
                    self.advance();
                    let right = self.parse_term()?;
                    left = Expr::BinaryOp {
                        op: BinOp::Add,
                        left: Box::new(left),
                        right: Box::new(right),
                    };
                }
                Token::Minus => {
                    self.advance();
                    let right = self.parse_term()?;
                    left = Expr::BinaryOp {
                        op: BinOp::Sub,
                        left: Box::new(left),
                        right: Box::new(right),
                    };
                }
                _ => break,
            }
        }
        Ok(left)
    }

    /// Parse term: factor ((*|/) factor)*
    fn parse_term(&mut self) -> ParseResult<Expr> {
        let mut left = self.parse_factor()?;
        loop {
            match self.peek() {
                Token::Star => {
                    self.advance();
                    let right = self.parse_factor()?;
                    left = Expr::BinaryOp {
                        op: BinOp::Mul,
                        left: Box::new(left),
                        right: Box::new(right),
                    };
                }
                Token::Slash => {
                    self.advance();
                    let right = self.parse_factor()?;
                    left = Expr::BinaryOp {
                        op: BinOp::Div,
                        left: Box::new(left),
                        right: Box::new(right),
                    };
                }
                _ => break,
            }
        }
        Ok(left)
    }

    /// Parse factor: number | ident | (expr) | trust(t)
    fn parse_factor(&mut self) -> ParseResult<Expr> {
        match self.peek().clone() {
            Token::Number(n) => {
                self.advance();
                Ok(Expr::Number(n))
            }
            Token::Trust => {
                self.advance();
                self.expect(&Token::LParen)?;
                let time = self.parse_expr()?;
                self.expect(&Token::RParen)?;
                Ok(Expr::TrustExpr {
                    time: Box::new(time),
                })
            }
            Token::Ident(s) => {
                self.advance();
                if self.peek() == &Token::LParen {
                    // function call
                    self.advance();
                    let mut args = Vec::new();
                    if self.peek() != &Token::RParen {
                        args.push(self.parse_expr()?);
                        while self.peek() == &Token::Comma {
                            self.advance();
                            args.push(self.parse_expr()?);
                        }
                    }
                    self.expect(&Token::RParen)?;
                    Ok(Expr::FunctionCall { name: s, args })
                } else {
                    Ok(Expr::Ident(s))
                }
            }
            Token::LParen => {
                self.advance();
                let expr = self.parse_expr()?;
                self.expect(&Token::RParen)?;
                Ok(expr)
            }
            tok => Err(ParseError::UnexpectedToken {
                expected: "number, ident, or (".to_string(),
                got: format!("{tok:?}"),
            }),
        }
    }
}

// ─── CONVENIENCE ─────────────────────────────────────────────────

/// Parse a VSL string into declarations
pub fn parse(input: &str) -> ParseResult<Vec<Decl>> {
    let mut lexer = Lexer::new(input);
    let tokens = lexer.tokenize()?;
    let mut parser = Parser::new(tokens);
    let mut decls = Vec::new();
    while parser.peek() != &Token::Eof {
        decls.push(parser.parse_decl()?);
    }
    Ok(decls)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_lexer_vsm() {
        let mut lexer = Lexer::new("⟨S1, S2, S3, S4, S5⟩ @ E(0)");
        let tokens = lexer.tokenize().unwrap();
        assert_eq!(tokens[0], Token::Langle);
        assert_eq!(tokens[1], Token::Subsystem(1));
        assert_eq!(tokens[2], Token::Comma);
        assert_eq!(tokens[3], Token::Subsystem(2));
    }

    #[test]
    fn test_lexer_channels() {
        let mut lexer = Lexer::new("φ↑ φ↓ ψ S3* α σ");
        let tokens = lexer.tokenize().unwrap();
        assert!(tokens.contains(&Token::PhiUp));
        assert!(tokens.contains(&Token::PhiDown));
        assert!(tokens.contains(&Token::Psi));
        assert!(tokens.contains(&Token::S3Star));
        assert!(tokens.contains(&Token::Alpha));
        assert!(tokens.contains(&Token::Sigma));
    }

    #[test]
    fn test_lexer_logic() {
        let mut lexer = Lexer::new("∀ x ∈ A : x + 1");
        let tokens = lexer.tokenize().unwrap();
        assert!(tokens.contains(&Token::Forall));
        assert!(tokens.contains(&Token::In));
    }

    #[test]
    fn test_parse_vsm() {
        let decls = parse("⟨S1, S2, S3, S4, S5⟩ @ E(0)").unwrap();
        assert_eq!(decls.len(), 1);
        match &decls[0] {
            Decl::Vsm(v) => {
                assert_eq!(v.subsystems, vec![1, 2, 3, 4, 5]);
                assert_eq!(v.level, 0);
            }
            _ => panic!("expected VsmDecl"),
        }
    }

    #[test]
    fn test_parse_vsm_level_2() {
        let decls = parse("⟨S1, S2, S3⟩ @ E(2)").unwrap();
        match &decls[0] {
            Decl::Vsm(v) => {
                assert_eq!(v.subsystems, vec![1, 2, 3]);
                assert_eq!(v.level, 2);
            }
            _ => panic!("expected VsmDecl"),
        }
    }

    #[test]
    fn test_parse_axiom() {
        let decls = parse("∀ x ∈ A : x + 1").unwrap();
        assert_eq!(decls.len(), 1);
        match &decls[0] {
            Decl::Axiom(a) => {
                assert_eq!(a.var, "x");
                assert_eq!(a.set, "A");
            }
            _ => panic!("expected AxiomDecl"),
        }
    }

    #[test]
    fn test_parse_trust() {
        let decls = parse("trust(t) = 0.5 * x + 1").unwrap();
        assert_eq!(decls.len(), 1);
        match &decls[0] {
            Decl::Trust { .. } => {}
            _ => panic!("expected Trust"),
        }
    }

    #[test]
    fn test_parse_arithmetic() {
        let decls = parse("∀ x ∈ A : x * 2 + 3").unwrap();
        match &decls[0] {
            Decl::Axiom(a) => {
                // Should parse as (x * 2) + 3
                match &a.expr {
                    Expr::BinaryOp { op: BinOp::Add, .. } => {}
                    other => panic!("expected Add, got {other:?}"),
                }
            }
            _ => panic!("expected AxiomDecl"),
        }
    }

    #[test]
    fn test_parse_multiple() {
        let input = "⟨S1, S2⟩ @ E(0) ; ∀ x ∈ A : x";
        // semicolons are skipped by lexer
        let decls = parse(input).unwrap();
        assert_eq!(decls.len(), 2);
    }
}
