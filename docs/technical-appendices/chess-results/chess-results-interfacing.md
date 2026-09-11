# Uploading a chess tournament to the Chess-Results.com database

Author Heinz Herzog, created on 2017-02-18, last update on 2026-01-10.

Transcribed by [Sammy Plat](https://github.com/Amaras) for use in Sharly Chess.
The "Notes on Security" section was written by Sammy Plat.
Last update: 2026-06-12 (synchronised with the 2026-01-10 PDF,
`Upload_ChessTournaments_to_chessresults.pdf`).

Upload of a tournament on Chess-Results.com is done using an XML file.

> [!NOTE]
> An AES key given by Herzog is necessary to sign all the calls, except GETSID.
> See the "Notes on Security" section for more detail.
> In particular, this means that only select few applications can send results to Chess-Results.
> Other applications will have a different source ID as well.

> [!IMPORTANT]
> All XML tags are case sensitive.

## Base requirements

1. Each user requires a unique `CreatorID`, so that tournaments cannot be overwritten by other users.
2. Each tournament has a unique identifier (database key).

This unique identifier is given upon request by Chess-Results.com, using the following protocol.

## Tournament key request protocol

### Requesting a Security ID (SID): GETSID

Call <https://chess-results.com/Uploadxml.aspx?key1=GETSID&source=13>

An XML file similar to the following will be returned upon successful request.

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<chessresults>
<result sid="140972164" status ="OK" />
</chessresults>
```

Parameters:

| field identifier | explanation                                             |
|------------------|---------------------------------------------------------|
| sid              | Security ID, necessary to authenticate subsequent calls |
| sidEncrypt       | (testing phase only) encrypted SID, using the AES key given by Herzog. Not available in production. |

### Requesting a new database key: GETKEY

> [!NOTE]
> This request MUST be called only once per tournament. If it is called multiple times, tournaments will be duplicated.
> As such, the given database key MUST be saved immediately.

Call <https://chess-results.com/Uploadxml.aspx?key1=GETKEY>

An XML file similar to the following is expected.

```xml
<?xml version="1.0" ?>
<chessresults>
<getkey
    source="13"
    sid="C36E85386EDD4994144FDC156B6C37BA"
    creatorID="13121"
    federation="JPN"
    tournament="Test Unicode  横浜 Open"
/>
</chessresults>
```

Parameters:

| field identifier | field explanation |
|------------------|-------------------|
| sid              | AES-128 encrypted sid from the previous GETSID call |
| creatorID        | A Unique ID for each user |
| federation       | The country of the tournament (3-character FIDE code) |
| tournament       | The name of the tournament |

On success, an XML file with the following structure is returned.

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<chessresults>
<result key="222557" status="OK"/>
</chessresult>
```

On failure, the following XML file is returned:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<chessresults>
<result status="ERROR"/>
<messages>
<message type="error" Text="Error getting New Chess-Results.com key (node /chessresults/getkey
not found)"/>
</massages>
</chessresults>
```

## Uploading a tournament: UPLOAD

Once the tournament key has been requested, the tournament can be uploaded using the following XML specification to the following URL: <https://chessresults.com/UploadXML.aspx?key1=UPLOAD>

For increased security, each upload call SHOULD be preceded by a GETSID call.

> [!NOTE]
> It is unknown whether an old (> 1s) SID can be used during the UPLOAD call

> [!NOTE]
> The XML is sent as a form field named `xml`, with every `<` replaced by `{`
> and every `>` replaced by `}` (see the VB.NET reference implementation in
> the PDF).

In all the sections, optional data can be sent empty. It is unknown whether the field needs to be sent empty, or if it can simply be omitted.

### Tournament data (mandatory)

| Field | Description | Mandatory (M) / Optional (O) / Forbidden (F) / Unknown (?) |
|-------|-------------|------------------------------------------------------------|
| key   | The GETKEY tournament key | M |
| type  | `0`: Individual Swiss system tournament; `1`: Individual Round-Robin tournament; `2`: Team Round-Robin tournament; `3`: Team Swiss system tournament | M |
| name  | tournament name (up to 160 characters) | M |
| remark | A remark (up to 600 characters, 599 enforced on upload). If it starts with `#`, it is shown in orange | O |
| director | The tournament director (up to 80 characters) | O |
| organiser | The tournament organiser (up to 80 characters) | O |
| location  | The tournament location (up to 80 characters) | O |
| arbiter   | The list of arbiters (up to 1200 characters) | O (can be sent empty) |
| rounds    | The number of rounds | M |
| currentround | The current round | M in Swiss tournaments, O otherwise |
| rankinground | The round which is used to compute and show the ranking list | M |
| sortstartrank | Sorting of the starting list: `1` national rating, falling back to FIDE; `2` FIDE rating, falling back to national; `3` FIDE rating then national rating; `4` maximum of FIDE and national rating; `5` national rating only; `6` FIDE rating only; anything else behaves as `1` | M |
| from | The date on which the tournament starts, in `dd.mm.yyyy` form (but see note below) | M |
| to | The date on which the tournament ends, in `dd.mm.yyyy` form (but see note below) | M |
| ratedfide | `N` if the tournament is not FIDE-rated; `J` if the tournament is FIDE-rated, `-` if it is not known | M |
| ratednational | `N` if the tournament is not rated by the host federation; `J` if the tournament is rated by the host federation; `-` if it is not known | M |
| tb1no | The numerical ID of the first tie-break (see Tie-Breaks-1.xlsx for the details) | ? |
| tb2no | The numerical ID of the second tie-break | ? |
| tb3no | The numerical ID of the third tie-break | ? |
| tb4no | The numerical ID of the fourth tie-break | ? |
| tb5no | The numerical ID of the fifth tie-break | ? |
| replay | The number of times a round is replayed: `1` for single games (default), `2` for return games, `n` for n-rounded tournaments | ? |
| timecontrol | A description of the timecontrol (up to 100 characters) | ? |
| homecolor | `w` if the home team has white on board 1; `s` if the home team has black on board 1 | M for team tournaments, F for individual tournaments |
| samecolor| `J` if all the players in the team have the same color; `N` if the colors are changed | M for team tournaments, F for individual tournaments |
| playerperteam | The number of boards per team | M for team tournaments, F for individual tournaments |
| ratingavg | The average of the players' ratings | ? |
| endstatus | `J` if the tournament is over (all results available); `N` if the tournament is still running; `R` if a key was reserved with GETKEY but the tournament was not uploaded | M |
| tb1_detail | Parameters for tie-break 1 (see Tie-Breaks-1.xlsx, column P, for the list of possible parameters) | ? |
| tb2_detail | Parameters for tie-break 2 | ? |
| tb3_detail | Parameters for tie-break 3 | ? |
| tb4_detail | Parameters for tie-break 4 | ? |
| tb5_detail | Parameters for tie-break 5 | ? |
| tb6_detail | Parameters for tie-break 6 | ? |
| chiefarbiter | The chief arbiter (up to 120 characters) | ? |
| homepageorganiser | The URL to the organiser's homepage (up to 80 characters) | O |
| mail | The email address of the organiser (up to 80 characters) | O |
| federation | The country of the tournament (3-character FIDE code) | M |
| creator | The creatorID of the user | M |
| offsetpairinglist | If > 0, the pairing list starts at `1 + offsetpairinglist` instead of 1 | O |
| federalstate | Default `0`. Federal-state code for the federations IND, MEX, KGZ, MAS, INA, BRA, RSA, KAZ and POR (see FederalStates.xlsx) | O |

> [!NOTE]
> The 2026-01-10 PDF specifies `dd.mm.yyyy` for the `from`/`to` dates and the
> round dates, but Herzog's own reference upload files
> (`Team_SwissSystem.xml`, …) use `yyyymmdd` and are accepted. Both formats
> appear to work; this has not been formally confirmed.

> [!NOTE]
> The PDF lists six tie-break value/detail slots (`tb6`, `tb6_detail`) but
> only five `tbXno` fields — the sixth slot is presumably reserved.

### Security data (mandatory)

This section is the one that allows the platform to authenticate the request.

| Field | Description | Mandatory (M) / Optional (O) / Forbidden (F) / Unknown (?) |
|-------|-------------|------------------------------------------------------------|
| Source | `13` for Sharly Chess, depends on the software | M |
| Sid | AES-128 encrypted sid field from GETSID | M |
| creator_sid | AES-128 encrypted Creator ID (as in the tournament data) | M |
| tnr_sid | AES-128 encrypted "key" field from the tournament data | M |

### Player data (mandatory)

> [!IMPORTANT]
> On Chess-Results.com, the players are displayed in the order they are sent.

| Field | Description | Mandatory (M) / Optional (O) / Forbidden (F) / Unknown (?) |
|-------|-------------|------------------------------------------------------------|
| No | The starting-rank number of the player (1 to n) | M |
| Id | An application-defined ID-number (up to 12 digits) | O |
| Lastname | Up to 32 characters | M |
| Firstname | Up to 30 characters | M |
| Atitle | academic title (up to 14 characters). E.g. Dr. | O |
| Title | FIDE title (up to 4 characters) | O |
| Rtg | The main rating shown in the players lists (used to sort the starting rank) | O |
| Rtgfide | The FIDE rating | O |
| Rtgnat | The national rating | O |
| Dob | The player's date of birth, in dd.mm.yyyy format. If only the year is known, then yyyy | O |
| Sex | `w` if the player is a woman, `m` if the player is a man, `c` if the player is a computer | O |
| Fed | The player's federation (3-character FIDE code) | O |
| Board | `0` for individual tournaments, otherwise the board number in the team | M |
| Teamno | `0` for individual tournaments, otherwise the startrank of the team the player belongs to | M |
| Clubname | The name of the club, place or city (up to 40 characters) | O |
| Fideid | FIDE-id | M for FIDE-rated tournaments if available and empty otherwise, O for non-FIDE rated events |
| Club | Club number (0..32000), not used outside Austria | O |
| Typ | Usually the player's category (U08, U10, …). Can also be used for something else (up to 4 characters) | O |
| Group | Can be used for something (up to 4 characters) | O |
| Rank | The player's ranking, computed based on "rankinground" | M |
| tb1 | Tie-break 1, computed based on "rankinground" | M |
| tb2 | Tie-break 2, computed based on "rankinground" | M |
| tb3 | Tie-break 3, computed based on "rankinground" | M |
| tb4 | Tie-break 4, computed based on "rankinground" | M |
| tb5 | Tie-break 5, computed based on "rankinground" | M |
| tb6 | Tie-break 6, computed based on "rankinground" | ? |
| pts | The number of points, computed based on "rankinground" | M |
| equal | If `n` players are strictly tied after tie-breaks, set this field as `J` for players 2 to `n` inside this tied group (their rank is then shown blank). If all tie-breaks are equal, the players are sorted by starting rank. If the tie-breaks are not equal, set this field as `N` | M |
| kfaktor | The FIDE K factor used to compute rating change | O |
| state | `0` if the player is active; `1` if the player withdrew and their points do not count; `2` if the player withdrew and their points still count | M for Round-robin tournaments, F otherwise |

### Intermediate ranking data (optional, Swiss tournaments only — team and individual)

While this section is optional, it is appreciated by players.

The fields are similar to their counterpart in the Player or Team data section, but are computed using the data for rounds 1 to "round".

| Field | Description | Mandatory (M) / Optional (O) / Forbidden (F) / Unknown (?) |
|-------|-------------|------------------------------------------------------------|
| round | The number of the round (between 1 and "rankinground" − 1; the data for round "rankinground" itself lives in the player data) | M |
| rank | The rank of the player or team for round "round" | M |
| no | The player's or team's starting rank number | M |
| tb1 | Tie-break 1 | M |
| tb2 | Tie-break 2 | M |
| tb3 | Tie-break 3 | M |
| tb4 | Tie-break 4 | M |
| tb5 | Tie-break 5 | M |
| tb6 | Tie-break 6 | ? |
| equal | Same as in player data | M |

### Round data (optional)

This section contains a description of the playing schedule.

| Field | Description                                   | Mandatory (M) / Optional (O) / Forbidden (F) / Unknown (?) |
|-------|-----------------------------------------------|------------------------------------------------------------|
| round | The number of the round                       | M |
| date | The date of the round, in `dd.mm.yyyy` form (see the date-format note above) | O |
| time | The round start time (up to 15 characters), e.g. `15:00` | O |
| replay | Default `1`. For double-rounded tournaments, the encounter index this round belongs to (`1` for the first leg, `2` for the return leg, …). The legs may be interleaved: e.g. rounds 1-3 `replay=1` and rounds 4-6 `replay=2`, or alternating round by round | O |

### Player pairing data (mandatory)

| Field | Description | Mandatory (M) / Optional (O) / Forbidden (F) / Unknown (?) |
|-------|-------------|------------------------------------------------------------|
| round | The pairing's round number | M |
| pairing | The index of the player's pairing for the round (1..number of pairings) | M |
| board | Always `1` for individual tournaments. The board number otherwise (1..max boards) | M |
| whiteno | The white player's starting rank number | M |
| blackno | `-2` if white was not paired; `-1` if white has the PAB; otherwise the black player's starting rank number | M |
| reswhite | White's result: `1` win, `0,5` draw, `0` loss | M |
| resblack | Black's result | M |
| Forfeit | `K` for a forfeit (win or loss); see the special-results table below for the other codes; blank or empty otherwise | M |

Special results are encoded with the `forfeit` field:

| Displayed result | reswhite | resblack | forfeit |
|------------------|----------|----------|---------|
| 0 - 0            | 0        | 0        | `D`     |
| 1U - 0U          | 1        | 0        | `U`     |
| ½U - ½U          | 0,5      | 0,5      | `U`     |
| 0U - 1U          | 0        | 0        | `D`     |
| AJ - AJ (adjourned) | —     | —        | `H`     |

> [!NOTE]
> The `0U - 1U` row is transcribed verbatim from the PDF; the `reswhite=0,
> resblack=0, forfeit="D"` values look like a copy-paste error (identical to
> the `0 - 0` row) and may actually be `reswhite=0, resblack=1, forfeit="U"`.

### Team data (mandatory for team tournaments or team-ranking Swiss tournaments, forbidden otherwise)

| Field | Description | Mandatory (M) / Optional (O) / Forbidden (F) / Unknown (?) |
|-------|-------------|------------------------------------------------------------|
| no | The team's starting rank number (1 to number of teams) | M |
| teamname | The team's full name (up to 40 characters) | M |
| teamshort | The team's short name (up to 25 characters) | ? |
| rank | The team's rank based on the "rankinground" field in tournament data | M |
| points | the number of points of the team (player points) | M |
| tb1 | Tie-break 1 | M |
| tb2 | Tie-break 2 | M |
| tb3 | Tie-break 3 | M |
| tb4 | Tie-break 4 | M |
| tb5 | Tie-break 5 | M |
| tb6 | Tie-break 6 | ? |
| captain | The team's captain (up to 70 characters) | ? |
| federation | The country of the team (3-character FIDE code) | ? |
| state | `0` if the team is active; `1` if the team was removed and their points do not count; `2` if the team was removed, but their points still count | M for Round-robin tournaments, F for Swiss tournaments |
| trg_average | The average rating of the team | ? |
| equal | Similar to player data | M |

### Team pairing data (mandatory for team tournament)

| Field | Description | Mandatory (M) / Optional (O) / Forbidden (F) / Unknown (?) |
|-------|-------------|------------------------------------------------------------|
| Round | The number of the round | M |
| pairing | The index of the pairing in the round | M |
| no1 | The starting rank of the team with white | M |
| no2 | `-1` if the white team has the PAB; `-2` if the white team is not paired, the black team's starting rank number otherwise | M |
| res1 | Points going to the white-team (no1) | M |
| res2 | Points going to the black-team (no2) | M |

## Notes on Security

The threat model used by the author of Chess-Results is not available, and as such it was never audited.
From what I can gather, the main threat in that model is a malicious and/or inattentive tournament administrator manipulating tournament data that they have not created, thus preventing Chess-Results.com from displaying results faithfully.

### Encryption and signature

The algorithm is the Advanced Encryption Standard (AES), using a 128-bit key, in Cipher Block Chaining (CBC) mode, using PKCS #7 padding for messages not aligned to 128-bit block boundaries.

Both the AES key and the Initialization Vector (IV) were given by Herzog and are not expected to change during the lifetime of the program.

Encryption code:

```py
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding


class ChessResultsSession(Session):
    #...
    def encrypt(self, decrypted_string: str) -> str:
        """
        Returns a HEX-encoded encrypted string (uppercase).
        """
        key = self.get_bytes_from_env('CHESS_RESULTS_AES_KEY')
        iv = self.get_bytes_from_env('CHESS_RESULTS_AES_IV')

        data = decrypted_string.encode('utf-8')

        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(data) + padder.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()

        encrypted_bytes = encryptor.update(padded_data) + encryptor.finalize()
        return encrypted_bytes.hex().upper()
```
