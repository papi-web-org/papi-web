############################################################################
# This file is generated by generate_papi_template.py, DO NOT EDIT !!!
############################################################################
import bz2
import base64
from pathlib import Path


PAPI_VERSIONS: list[str] = [
    '3.3.6',
    '3.3.7',
]


def create_empty_papi_database(file: Path, papi_version: str):
    match papi_version:
        case '3.3.6':
            b64 = (
                b'QlpoOTFBWSZTWZodmZEAE8l/////////////////////////////////////////////4DCfNe706t2+'
                b'xvry93p3Ryge2Gma2Zvr3eu9tV32UXj26m+5ve3vN28+3c7e9LSNGSWxqs7dO33e5LudwA00U10de+9m'
                b'++fHeDT6y2sdM7PdeHV7NGmnu6x9bb7tVV1aA29Hdt93UPvbl95Hdt5dRcys60PgO6e0vc2L2C8yA0SE'
                b'00gaACZqZMT001NMp7RkTExMI9EaMINJ4TTVN5DU2g9NqgyekKfoNBpqbQamyR6U9T01PJB6Tyj1PRpp'
                b'qB6nqNHqGh6nqDxR6aHqh7RGpskGagZEQJgTIaNATEaZARino0VPGm1NqTU9ojaiPUbap+qNk2pqGaei'
                b'Tam/UUzTSAAMhkYBGIAA0NMgGgwgGmQyZMEBiaZGQyAlDRRpBCT2qfpSe1Qb1T8qP1TNT9JHqDQ/1UGg'
                b'DI0HqDQB6h6gDQAaDT1BoAAAAAADQBkANAGgAZAAAAAAASaUiRoRpkymTyAiPIU/ESPyamkb1J7VG1P1'
                b'Eeo0bU2kNqB5QPU09GoaBpoD1D1DRoNNND9UA0NNABoAGgDQDQANAAAANAAikgmmiJmmmgEyTJiPQgaj'
                b'xBNGJp6IxNMGhBtT00mTamnpGjBDTRkZMgAGjJkyaaPUaaaGh6JpoaAabUGjJoxAYhoxB6TNTEEiRAQC'
                b'GkyeU1PNGk0yZPSBNBoU8mp6mj1P1MSMnomaMSep5TaIPTU9IZNMnlBo0PUGgAAAA00AAAaAADIAAA0A'
                b'Af/CBUVpHB6XbpQCr61kNW6UpatwivSit16fgeJO73JDLrXIjxPT+J4PpagrqGHieFPwseMNU2cDiLbe'
                b'dEDY8dXK2OV12LSv3pJJcdfJl09TNq59Gtr7Gze2tX56MkGBBgCSA+MGDF9K79P0++geogqLVtilOgXu'
                b'c/spHzNRVU2WMSpdAxepYvlK/M+VHRt1PHuSYQk0BJgzWZUzGjJDKTdkOZ4NvPz+7l4Wpm9YBbGGAD/E'
                b'TfQcfSTy2TAAENHSzcApNRRUGZAikFC2qTGV2wcZxynzM7qCb8auUMcF23j7e6u27WuAcjBQD/OQaoZH'
                b'MoQsAZJejcaOusfQyVrAQNra2Vhpp6enpau0Wk0uhsbOka1/n2NpoLK0s7S1q62tldDqKvVW1tceixEy'
                b'ZiLQAaABSZ8J1sCQTABDANA12ALC6hdSxWNFSKKCg9DSVPq9iRslaRWWXu4VsU7xZMAn9MjJCAHZECuD'
                b'CDDuoDt2KZlDKpQ506hwD8hwNobBJjbl3Xly1O26/d7ygmzmWV45u2uitkpkO1xMjDE6i19moloRBZoI'
                b'eC98Zar1VUjC+E5WGlUiyCIozYQKoKwESSR9TENtAlcZWwLRptVtKycBOZCtookUK2gnLSjQgBvsBNAg'
                b'IW4QYhVDJgAT2xgoBDioEJN9IQO2TY7Kk20gTqIAW0JWSB2PUuOJSpO/Qm53xdlMCbk1+VMMJNWhhBYI'
                b'gVKNObBZ6c9gqqrXeyppELKAi0LWLSYgIY8Ry+ZMJjAo1YNhzS3p5e408sb8+HU1OlQgEgUSRiRhJJBr'
                b'VoVARYbuOh2OaXwtNtlJhJEke+QEzGacMMNyshNpQJpGDCtWILmHjcphhmaF4RLHcxiUswMasSwhjVmE'
                b'zgaokyZmLq2+Lk2X06e0GWBaijIPEqU5D1NTUUScpUW14b1NRWMK2rSkZiaS0v6Sg+cP3SjlszPOyG6M'
                b'ixew5TBjSAcmCYV4qFfUXMLGpAogFHqoqEohBB2UXzmk+zEg4tt6ENzPDb0VnO35HCzdhOTNDHYeOBIB'
                b'ojJ2TKyYGVGAoC5MKE42XP5+xsvPAkC9SpkyKNGVQM6Z0E6OJWTGmolSQzqt95sNDqzpQxaEdks0u1kc'
                b'Q3kEiX00plRNlKyPjWUVgXdfNncB1/y446wIXLfBlgyPgaMDFz0D6bvWCjiAaKR3CGSUONlIWYISUIsi'
                b'A0F87UJuaqSTzsBUQm5t7m5dKBCEhGpytmUolLVTEgotyyBZkwAbWUaCBccEcTIElyWV8ISUggJioHtG'
                b'1PGUFI8t6SSK2hcxoW+0uBgcLwMDwWg9MxeoZ4TPfmBJ8ckhtE3BVARSSySGygGyK9xCRGQGMCJ2DiCp'
                b'CY0aMIpUoMSmamqiEY6JvHAS4xTOBitaSLLXCkhAWWsoZZYZY0EmA1kMB9WwAnSGEDDIcVgG6hNUSQDg'
                b'MzVNKwQaaRhjAplYaokkDaTPOsEGgUWBrg1MRFuoyWdFhc6U7C6BHAWChBRpvtmtw0xmIOTZpwYJCats'
                b'32nLNE0YOGZyuRZSSg3aaGBCxo1pZV41wMwYuvyOLdBlMpBrqdmJkgeWeLnm4yxleX1oCmbWInUJJGJM'
                b'J2u47jhw7HxvC8zzPMyx2Ox2Ox7r3Xuu+zV3Y2gdMgOeI3XZJMgDF0Wkny7WKSEiIAHMpYJqRojS6mDm'
                b'YyHGLgcQaRsxcDjDcDTFKWl2XHZ55Z5gZ1bC1bLW1kJattdNxlyPPmWSho0Yxi22hcXGGy7AkpSFA7xC'
                b'SBRsuhSkTEulKRMQ7ljHC8MdUeGOgdU7GqckeSPJHsjlVeeO2blXtVdsemPcDyB7k6dXRtbeJDsEnMu5'
                b'cZb/8+Am/bAm/nUqFZKQ22htE7MmTJTvVxW2VVKtbpukplpabpqKsKApCkKQlLdN03S8Xyc57qowLEFU'
                b'pNhxRASEpPvXhhiEkSEQz5YZje1KUQM7sGm8qV+/KRJSdTwOh0vWp3Xu02qqKrWqZEULsJwqJw27kYYG'
                b'pqVK14ANhi1KlgttFGpWsdyDrLjNtm/GwNBp1i1Mt2Wmah8eSAHgdVddfeVVVVVVVVVVVVMwb12Cz7jg'
                b'zN2hQzBc4wAJEbXDLHjgQj+hl4aEljdmKZJLExvH2zA6+S9kOt40Y5WEEY4npTPZ+xvbPqb6uP4xhFFd'
                b'4FusJ8cBMoyTrIYwFJwSEkiMWCZvBkys4XX4pIAkFQZnKSlzXRW42W2orva1d/vaXAz3Bvbvienxo2MI'
                b'EUWUcYaRqAJqSuDoElk6YTTYSaSMknb9am8yGayJCCqFqBHUQikiFUrlt8ppoWjUTGcnluex5vi+X5TY'
                b'a7mufc8fRo0aNGjRoyaNGjRowbDFsMOixAhtYugQpMDYRWxtUnopwS4lMzbVqTDNEBdilhDgKjj+ONjv'
                b'p43pKSkQ2hpeDwKR7930P0POmed9Z5N2+Rbe5F+24IbaXnvOzozg62mbWUzMTMYjEYsRiMRiMSIJmSZM'
                b'EEyJQFBGSiaYS3tZWZzOb693W8z9/v7bB9KmwnvErr/07jEqQC4UAkZtv4/i4vN8buuf1LkaIEJQc7g6'
                b'3zMp9e0dgwPWtE35t17RRToa9kKmEGboEoaDKh5RhAPStWs7PqlTkEwtueHcpoZbY1WCIgIRfogKKQWt'
                b'jtmQkwmhiogRGFkkIMIDeBgBX2DYA2DsqpKWpNIVAkgiRdKCdSuWkv13w1g6fWm6yGRaV5kcGx3hi05L'
                b'EQsrD0IV68jJKkdf0nHoIHpY3eVzOrF2Dih894V9BtXji3R0tx4XRUIQSTcGajQsg36KI34SrWLXg5zE'
                b'S5N2qdTexyY2Q16K8NNIKqgIWs0XL3kdypmmmgxDFa8IZL85gXrxBWinDwptRcUOm0ePtwdCFHuKLdDG'
                b'LogcaXEzPW5YGarzBaKZypCLbR0SKhxx5cIrAWv6yRP2r5fB8JKva7Svg7z1eSfIqivBi3CZLMQluMzx'
                b'As8yUmNsYbt2oQlMuThNIhCCFY0gojHV5wKFflAU29hLafAcEFN/maU9PFsyut0JQytlYae239W/e3d1'
                b'eemJA4N1xmBsvUSbS0pxU4BunCozaQUifoppd7ui30XvnG/pJaM4G8v5h5wuFw7vfRPE4srQycxGtCIq'
                b'ExN5TKpCZ1t7JzlLSU6rHM318kCTmKCXqaGoc7d2729NhaH0neFuMKv4NNW1ueu7iv4V5X3nC2mfst5Z'
                b'aXX6988fXT56+XfbB9sX2tfXL7VXN2+vH2tfPLqmBEWvOqBgUujQEGJ3xNRkWKCgosEYKCwWLFnl59I0'
                b'dEsKEB/d8zvOFw+TeHTtfaCwkLU6l2NwVOxp04aEksxAP95Bqegh9/E39j6WS9JOPzejO2fb+hSRgjVI'
                b'xNFvgWd4ApmkyC4UJuI8gMAQDpWCAoxkoj2G9ivdDzfFxeb7TzkOQa+v2WbyhI3zU8LJ6TamGVi8Hj9H'
                b'semxUlrLHYziBPe2+eSvUKQKXc582bNmzZs2bNZdXg/JavQ4cWz2HrdY6dcoY2NjY2NjRRRRRRRRRRRR'
                b'RRRYvxeVpIsjlQmnjkPLWSDnkWApg0ULy2lNWwRMV4VW7q0dyneS9RCBvoBd3eN8FwAcuAMYI2BoO0tW'
                b'jRo0aNGjRofff3KRZA7+4KJqsm/QOb2SiROUn1w1q2yJphfWZzRqqEdUEa/kRYl5TJ8CzWQY6WeG4jIa'
                b'WQBYdJkBRGJ9ZqEik5siJqDn09U6QkQKck42Tbt27du3WWWWWj5fUt9TqdS48XxfF7viOmLv+TnYAszP'
                b'Ov4ppE2KbVexmEltgcFEdQnHOPx+PbbbbbbbbbbbbbfD8P4ztd0Ov3N4B7UyJdgVS7wkthsObmQN4hCx'
                b'AocAMFWMhoN9TlKDQwA2xbtqqqq3GMh7azBYlUb6Hfr3AwzJJtbrIEDyAYgBPiBgvObPPcACtr2bMqqu'
                b'9vb3hvDoxidDOgmTf8DxHWl2QSnE3TZYAsJyfK55OATleN7T4EA4mvxLbbbbjxfF+M6hl1zPfxvO8/Iz'
                b'qQu9fw/c99IsaqZugbp75L3gUhMC3bt2wxjPB8HuOiO5Hb268gFdBbTp+D4rHUM+nvkjyOJztWoBTyqL'
                b'R5eNwyDKBMn87qznElDLfygQYo0SU3LNn/NzVLKHNzqE1GzjOpNKhRLSN2ieg005CTMJCIlQ4UiwiDQD'
                b'BIJF6ZNckzmcvsQ7xQoJQFQkyO2kcnJXKbgiixyme/hUcG8ImB3DHx0cDqO50bddFfwWzwqngGFHmQ6w'
                b'LUA1mFjFbo4/QMIfSkepGdO4YNjzXB4vi+M/W4dqzz8F6mkIOmBvZvXeu9hLddgWv1/r/Yccyh9d2oaT'
                b'EZtB8bxcqsBEsczP5VKJJREU/QCATtgkQD2xhGIfG0vdqkNWbKVgSAWHXn52PsFiDI+PbbOrT2mdyjFN'
                b'AEGCtwkVYkQCC2p1TSqMB2aMwjMGFVxyU6+Epsp1o34xpJmG7C4yy4d0u4EjrgeFLshlfTYYpXy3x5+O'
                b'U0tty4o9XhXlF8uB6MwwHovfoMDVwaRpDDXBICIT0whoTGzzPLeKdMyR0FCsrt0KVQg30A8MIA1wOBEc'
                b'UrotV9W4k/3r8NC1uYq2rV3DVqcrwOL2HC3PPXeFNG+cQ1Ad3d1OfoTERyahWoVqFYLBc0M8WCwXjCGo'
                b'bpulLdUxjHL4IbLLFypIn4apGP1KtUNUVVVVVEU9S1BEFUVumZ/SfltWmOxiSNdhgcTAhENBMxkyIiZK'
                b'Usdw9jrlymzXivXhYJ7k1y5cnr0T3FuBEFxLcdI20gE4nCqqsCMZCXbdLlKOu8iTwOVesrJSkiSzsACj'
                b'TjUSBVVcjHgjWy/WFKKHKEbZLFYTG9uRKVC8iuVbnrFmmaQu75w6rvC9Vu+TG5EQYy6jBgngc9/Rslqt'
                b'KRuCIdOQttotdFSpxCCsoG5kRQHsa5VueW46itUHJ3ZkhuZEVLhuRe08bsCeaHwzofNFgUwi4esJCB8k'
                b'+gkESAwPF+ChJnhFRJvoSiTh1PxTN1fHqSPhKyqQmjsmg5jREQkmmlj47sS4djcnl8LCXJh4fN3pSYsf'
                b'elQZC+HH5Fm2cZ1CR1DjOocRqmMsLCwsLCwsLCwsLCwsLLcN3q7Pc7d12cdZOxyBQOb4K6h7yjod6SYR'
                b'vBJD2c1ZS0BTCm7lHNPK5Z0Hvksa3NIN2Y66DhBmAQ8OG3kyZM+fPnz54IIIIIIIILLLLLMKV86GEONc'
                b'GxiPK5vdeBTQVbtlxWh36M7I5r5oI9ow7mg2DbCoqOzfWNU6DAUHSNKU41pNjg6B77eKXAQNceOi72Dl'
                b'9cQZ9dvV3mcwd+NsYsQIBtBKd8dvV1hYsZbS8sTaY2dencrEL08oTtuYNK0RPaO3p6mYc3NQeN10YwHn'
                b'ORFcESaElyXKiwXrDZ4xyFTswI56l2fbRHOcIz2xzbcd+dD2vmfJL2ktp1MzseAZIIvTtBNgbmzyOwdV'
                b'DiO66JUgr9YgoD900ZHrxktuBbaKR46YwUXkr10Y5cM/hUacoFJug4N2uMg1M1ejIvJ0+FgNhOggwhEC'
                b'IxWsVAhDtq+ex7He3uHh4eHsOZCOzToWBHHG/HHHHHHzRiPYUEaaajTzxTTTydxEBrWkcsg8AZ3R0A6J'
                b'cAUzYs5tvcHYy9CuAvmOOlEdJwDlRrvEHi1ecy9wDDUIOtzgzcFIQNS5vFEOy/ZE84rpyXFGg6bIDxUM'
                b'PJldMvMFWMSWA853JczXMNe3j7C8RcXNU5CACbI4BxV4w5mL5YPHSIIOzZjtNu1KHbRBqeBI7Wc3tsrF'
                b'ixYsWLFi7olalalalalalalalalalaJWpWpWpDw5DwzamdzYo2GXGaoh9M6Xo0aNGjRo0aLWta2GGGGG'
                b'GEGUVu01cdi/MOZjXRht85ojLmsux3Qwhg1R1b4ELkAJAra6HAw9e+i+fwIO3lo4ejzkaBfVYfHMXNfv'
                b'IrwdbWyBg2hM0nQbM6Qh1wAjunlNNwBVwkJatg+x5fLH1YgEWI0DmRoiiJQe6as/ASR19DjgBKp4SBVV'
                b'VWLyB31GjqBdSndbd3YofGS2+294944DJ14apYc17RNkl6NH27LEPfHE6GKHADpW8OA46p+rXv8wgXfX'
                b'lv2HXAHLUCttEg96XFmEarO7ClLRq64qIIuLRhPB8MjWWySrOjPZ3li5YrEb4t2QSBSAYYLtuzwVrzQB'
                b'P3ZmPKJIUmMyWEMmXFy0xmbTGWwwcjjrKUmdNnZrgcoyRUdj3jBsktIIqaDTwVKxowP6fGQTZURizAJK'
                b'c2mmPB2hytTADc2oHp020SVobhLFUdOxSAFdCrqbGrbfb+A5WDW6bu7jiLrLWM+FXva65xGOzRCm+DMN'
                b'hfgSSBLlZp1N/VTpPix4lLySkpyXVBkbWvEsBmMlc/nAtie8c0CrLXXIq0jKUmxib37jSV2ymQGEtU59'
                b'u168WwtohKEZ9LMl9E+lKxstGDU5rHOYjJIC2N0bZFPsiNhh1jsWwtdx4uUvP026hGSQ40sAlClotkGc'
                b'Kx91UffMJ1w0eUEimmyKJjWhXB5c6FtjwqFLEFtCLmbYEiOKari28pPXDGShlfLsNB1SQkC8trnilnM+'
                b'yXsqJnPKFT5e/U22NttttsdWCiRMxl3mwqtfGcfXLIbyG/XFRWBYPMcJkmBydosC1PEtqIuZoiIiL16+'
                b'kpLGGvSxjTaEVLeVSQzOHLMDYVjwaeqdKy6tiTHMvUIBLFly3TCnWki8E6H519rr7ICpFtuh6S6LXNC+'
                b'ipKtGGwvVPJpGF0VU0qScPLeOIoXcIEosul6iEFM0WsxP2ATI0qOnI5DrpSKBljZsEhOSIVAYQc3UaCY'
                b'pK7RDK4ERckrGm03NKxhpta5cpVAOZTAlamAqb99U0wxBSqlNVwRQgaIBUSakdoXO71VDEhcvlCeOWcW'
                b'M2zcW0qKMJp7AVElua28XCXTrZtN8BQeLVyG1SrISBhEkwfaAIwMSmIDfwIW4gUM8wyB5wmyLJhN9GIU'
                b'lfKaFYatWXZ5WyKEExqBMXeHhkYTlyDcU1pVHS0T1mkxrLCFePMwWlmwVxUDMIeASKDgKaY1SoN2S2u1'
                b'RM6heY2l+Nx4mNriRVcGJtdMbvPKMGi5h26ttIitAJTUXZI7tqhPskkrKUVIhgRZejWlD2YsvcVE5HPl'
                b'I1IgSIWaMSa2AJVUjnBAQomIUyRCIEQs95BLA2YCBZpE0WwyYYFSJyzU7DVA2ZlGbHNW5FuQbtxgar6j'
                b'7o4dCWZJ1GIiXfYNXFTC6miZKB4mO0b5OqrIoFJttOV8ko1WhXJb2PdouNOiEYmIVdsIVW/eVWlsEilF'
                b'53LLiCSTQzThdkAbnzh4iIuWIXhQkoREa1TXymAVWLlFhJ7JAr2gPjiXGaWuKxTDOLDcO2WIEY00iQxU'
                b'ZN5tYJV7kQqmPJmBCL0jLH7mJbLZpwzcWbzbWgGehEgztVu6Ckr4vyNkyDGNF4WQBGa+2lwrzx4GFBgG'
                b'I02vCgLF5EC3O/V7jO3O9OlUCPVdD1bCTYGhqbBB5/kXtGnJ8YzW9UYrLfuYPHJwegPtIR7/7Z0elHNj'
                b'C72/YpkxxA/G9d+gu+V+D38jOfBgk+H8WBzmpY1vjJj9PJ0VLsTHI6BEJeCbYZT2Ro+L9VVcGCrrkDJf'
                b'rsEpOR1bJ+6QBQQ9ORBA3JED3NYeDZViAdUqkhYIBDLO2UBbIJkZGCu4kQfwZpgxheIwTHL8CBkGyB+G'
                b'DEd8c4f5jh/9yNrB18B4+2keT5UhEUTq7wSDq0DcSaTMTzj3m3XeOX7+5HqiABEAnO4+vjeEV8GlgyEO'
                b'zd9Jm5WWD2yfP+N1U9Xr97jVO3jIapJFdYdEZAEOOVqYEPpkagwMYyJgEgofKBmIdxg6Y9zEWcLaw9js'
                b'lVoFggRIIIIIJoIIFWTv0j6+hjBMqIe/ret72GhIo6KKKKKHoH37Wta2pixYREbrWmZ4dJISSEkhJISS'
                b'EkhJISSEkhJIqZmIiIiIjhklERERERKSvrLGskY/D8fVBtamSCiY8HIivOykTAOuaBSaF7vLHpxiOq0I'
                b'ANt0xC0NKvcPUSCTN9oQFLSSqCS+V+SzHZU1V1MG0NpobkEgxakhebk958n6Pz1vQ2fBp4J0zYfa37Pl'
                b'pfFPIHIWQQgqNSKPFUZblj8kEAzCgkDBFuacIIuWnVSGAzZSxgVA8Nh5zTSZITfTkYheGye7ZXRnfRc2'
                b'zwGsy2NXHOcCjnZCaoYhfa6YZ6L5GmFTNK+rSGHCSsNthXVRecyBPWvKhHUQVBJmkqT9B9GyB7ek7zrd'
                b'TG14WWWUMhh6M8xZCGukZD2KcBNpHs2XCPfuMKlo6IAoGM50CzsSFvtBSzsmgJVUSPN29dd8zq97Bo9Y'
                b'bvEcazCBwkUkr12c1jaQnA9J5P0mwZw7ToUNZPStTYECuGBAlYQCMCcQpcUisoYYQiCFBdyhRZDGs66m'
                b'bdMam3Xuei2PyauBq1XlvXeyyy7j2OD631NmzOyiqIIwbzWeJ53p48g8Z8R961r2KuiNeoQmEkwOyaDv'
                b'mSsgBfJ+13ZYuj7jamdW+R2fVlHV6roN7yur1frqO3GhIMNUdroiXa3JJHG0E2EM7QZIfXpDSke5dI4k'
                b'nmbKKM/S+AzDow1hDRqICocnCJmQBlwL1m+SQ2eglo70klAr5+HpPjBL9LPBn3DczxGxnpEC7b96Pdux'
                b'pBsHJCMqfvDFCEDeZvPj8nLpqNEauSGfgXWIIQQohxUmSIQh3T1mGGTZ4TDxOVlIZKZQpSrClQaFwIIm'
                b'mRSHzeZmomQjNtMxSKxVVcFQyxCixJoGWIIefaaBBgZUY0/MVqbjRqJAogytzAgTID1ei7uU4T7rHVwW'
                b'qrkKq/8x4aHBxpgiILIdZMDEeUFGAJSTp5U+IZ5N81x6TYo/h91O0zyQXXitErAZSzW6XP6J0ej0sY6W'
                b'Wr/TzbO3fe3Y7b2s7gELehEuREF4gDWyJPCfSkGhxpIWGNlG+ZHcYBkZGOY+NkTTZE/vNkj5HQ3MC4hC'
                b'c8D1MA7W/nMmFnBDaEt5iDIxHp2jYwwXWGdpdZh6Bq53ELO11ObZ1U4TIE9AkKMiiMkWQjF7tA12QgbR'
                b'r2ALsJ/F2vFwLJGKCvLdLwObt47p/3g3JQW9pDcf7D3p35cL3KRE8CXqqOXiB5m3vuW5v4mlvt8b7biI'
                b'3XaeDtdt7fkc3ulLg9lTJJkYgCCGCEiEIbnJbzxm1qnmYT+hPuwJyeLUO7ug2g4SJn5y4LjJz6ufkPbc'
                b'vlUUUUUVBAicuUAvyTiAQBPcB1Qzk0wLRmVuYc+pt/b72B8+ycOHAcGbgOOfDtsH/t9tjq4gEWlAsDgU'
                b'5FSYQUCkAUHCMtemQCoMhJsQgXSaEzSMkGAQE6EwggxgqjrLEAFL/r5vvY1TztFl7Zrsf0WERBFVM8ig'
                b'7WQwi8mjKBuZobmZgfZ4st7HIxPpz8lfMmsAEEJYyGVBg7/r0JDDJFgEEjNDC2gKLAsaiitxLJCUGNse'
                b'1zFAtJQEdHRxTbQVHlaZHlxnj5nUdTzT2Bj16o+9IoBUpG8SwICRhDpUpBSQts+sfL6PIfKepxnn4Gj4'
                b'37X20vEa/rf2D/Mw4bobzbCCUKBoEX6f6vG/X/A4ODgXBwGLj/8w6HWeoszzHD9yJj081FRfFQCjMygM'
                b'TIESUT8nlTFDTNZhMe0Ox+3+H+O8wAHcMAzJsXwrjIuVIU20eEG2Q2Hh8knooBtrR2ex8/g45AnDWUxc'
                b'o39w3AnVE0CIiJIevAD2CCqoqiqEERBIyICWNGH5yU4lNpOOJvb1mpvBzsH6vcUloPW3XjtPC3kgtLy6'
                b'Jcpdh2bh+7AZX30R/R4eLJS3q+tzhxvsYuwiVukgs/H6BIiHuH2fFyUoUQv9jBYq3wzeXxFrbv5X4u7a'
                b'ePM6fpj3u7Ojd/B4rCadOnQhDT1bnp98aiD+baeaaHj7W/Z3/2r/y/stw8w9uR6Ly+R7v1p8SZaippA2'
                b'gDs2kCG2dlH8/6IcSHDV6z36mh9YiBc8eIW7/ui4xAoCdW48Vz7LnmP87TitC+51u7KyDeShDCb7i2my'
                b'4+9nW5Cuy1Bed/OZi2NwJ7r+vD48RKjhsQP0gOPCMcMAV8ZND8IehFVAqsQVqE04JO6SENlPyMtjTp+u'
                b'M0O0MQdQfMMPdY9VDgP5kWXncvyqHl8iOZ5lL9b9O6ToWZAov8Qkds1n4efbkn19diZHPyuz+XNwnmEz'
                b'72T9/9XNxvL5IH++lRNkXgzeqTDgyBzJqmNJOAnYfCzNbOviff2Pa2KAIhJ4VeThXfoQiBiCHk7yD2f2'
                b'0eMgMUeZzedzprnakMZQwQflsD8ViwsQcJn1SYZA0Os62tTJ75CGqyagyQUkx6YokpMC8zrezMdEwSbu'
                b'3bt0me59oe6ShgRGCYIdmSuBiSDwrdu3bKABwSBFr/LJtQ5yG1CoNdddZOjXCluEBmpppmnAiDEMGStq'
                b'BA5Z/tI61GuuzX9pGm/QCACsypFVWS1WTtEaS7kRIrj02HWio+vty+h7u56iz6G1tcii1g7TU8Tzulq/'
                b'Ev4Ou8bCPjoASI0N+rIcjSSvPkrs9ixYfDpJEIpYgSqyMsuYkomfol79Hr7d27cpygrNnMTEGG9ReSFM'
                b'33du3bqmNghbu7HjLBD7774bEiRqCKMCxZTKBFuORxxsIdQkmX78gq6678QhndHA1xy1ixYw+QRpLkXt'
                b'kQ9bvcjRqNFMIXGEQzuw1OJxmAd94wHN+xP5d5jmrGrq6uIaccVVeilinQK8zy1t1/R5P2fg/czt/nR/'
                b'QhNV4MF7C0l8swr5XDcm7LLPMR0SNLZhEtBCGp1F03Lurdu3iaxGsbVmJbNqqq4hFQhFLADpHF/rXXXV'
                b'ULg47Oxrrr5iFXjYdAaFcYHUw+OPEyrrr/DOOLkU0083SX0BfQhbhmIc7c7lGauu3+zpUI2khMX4P153'
                b'+W222/XrcWfPPUZS0gyCYGNyrQWrVqgw4BNN403RWmrt59Rrp7Vry7bfwg1kCv5MAkr8oly8PT4EJ3r1'
                b'7VQvxfGuIKUL2cFzm+clRbbLF7nTkDZlahkkClAQAl1gRTGOAzZcxXr6czv8ewmN2Bzk2r3/9qQjd5IS'
                b'1R2vZ50bdu+BOQCAL4B9oQZLEvRAlt2vZyzjlcy1309y5hdKj/K6mghR1gwgGggDTQKzGFfxmZ7g1wI1'
                b'al3EaJ8JIoookIBOUg2qghp9xdlrxO5b7gekkkk3hMSWs0gk79zo6RtTttrrEKhZYqD2jv1110lTAm+C'
                b'hBn/ZROBhjiu0pdfM7yi5LLLbvP/QgIB1/VVtSvG/mkkkjiIG0EBIvBAR8mtT7PsPyG9L3/kJ2v/F8ti'
                b'5GCjfin1Zh/01U6MF2Em0EGOm10yLDGMqYxiqqqibCqiayrWVXBgwWYwABzl1UkzBdjXjWWhrkUThBi1'
                b'0JyobE+LLU2zVly5XH8uXBZy2csWXLMMrVTi6Qs2EyIiIlKiK9e6jhwp3f+bzzziIALKACfhqqkwMmow'
                b'YMDj+DBJgwUYIq+C+MDVTo6WA20FULDwftLJLwe61uBwXSDoiikhOwEBu3cS4XXDFnUAnuEIHZIeShAN'
                b'JEl/Ns0YVzIBKtWaWY6CGqqQbbw1JFnG4h6jYZWHTzNRZAaETx9KXSmikfGlNQwFvtGXlPleBzqALwxp'
                b'hGTkFCgkUZFJFkOOwFfgsGIGB6+vM+FG0lMQiBIF3fn80jztRwGH8o1rncXqqsPdXAOF6zAyjEBe1nrU'
                b'VV03cfF3EHt9MIMWLmWF3DALrNCBdB6vpqfOGvu09DFzu7+NxU+nQuZdkCDq8yEl9A0gU2YcSYmAx15b'
                b'9V0+YOVjzRP+AP7YSAB0EAAA+gQdA4rs/FgzZ9kjg13+LJVbOLGLMM5AZsaUhTRBCZEKaqDxEJ2d9RIM'
                b'TDXdUutKbG0bAzvSR5CFpeb8t/tUhB/93vQ8i3T/4rM4Bb2GEC6h3kIuYEwds77wWiJP0vuZe+qfjxqo'
                b'AJaw6y7pMt+WVf/dYkQGeMgS0wDHnUQhpBSDYENGGhdMHbeerJgULqmTTsA9HnWkaQC9VXCWln29abUi'
                b'AhBjZTUFzP82f5XwCYLJr9imIzNBHBP9r4Mpp5PDKSANLf4p+Yp+zSKDOk+E7rgXqRpyLDdcu9dwANXA'
                b'cZKRhQDEISbbYCKl1bcKknsA7yJNbCH54Vf82fNiLiVoTUVTziGKxpUalVWl+ohXcjDTGCQefG+vYczI'
                b'dcb87fgfm7Kd0gRdaQLZYwFkxxiFkYC5FPL1SjWpiK5KUKCzZpOPFeubutASYaGAIWPS6Fc6Wjh1M28Y'
                b'Mc5hxcVbXxYjiOiYtxJKIjILWh+MDa0oGjnqChMajMWtNbKCAbwR2gNBh2S5GyHMZpgZGlyGMISCtaGx'
                b'DF7HXO7K2UqZqkVCqV0w0Yi7GKjV1TGxISN9oQRkSL4CiQqFrICDEb2LNK2zsJTvFUm1ALbhV8XduZR2'
                b'qNjmKrCNuBDf0dHotG5yCWCJehDEW33toCMN7bNC8HdroqAyMOZVTmP+kLeKjTpWW5bbwdpTeKJCcvUs'
                b'3uUuy1VVVVVXU4SRZmasUmstCJcHqRwdyU0u+SmaBFEzLsoczOiIUQb6WU30XU2W1yvuhWURfF0pPaVN'
                b'oviFERERFqqqsy0NrhVVW4T2iIZDrW22222222223LGMW222222222222222222223G3ztzhFhzlk5/N'
                b'm3OJjn8nLVttt06NOZAkuZOFEIUvgFhDTOfCxEZlhoQFyc1LhELiQGTo61N5C9qhU1MetkqxLAsAnG7i'
                b'DU2Vf/SQvb3wRe6/P9DqZ7TPZ7CYx44T7BCKisiyBcu9pwt/Vnd+U0BoVpNC7pj1GJiBtzQ2FBphyK61'
                b'92jd6HNUbmfgJFmfderPOB0CGpbOL+j+/yk7TUo+j8li8Dz2x9Rw+W89f18RjBxItLTMJpppppppppsZ'
                b'lOQSqkgYCNwIQgQjTOG6L6AkBDdcXseGtcK8luNfd1irlFhNPuDZncuGIYu4QBmSu3mhStDGSAK0IhTU'
                b'+zaqlQlI5ElDUsP2aF4uLXaEHcZXNJxHZWe8+pZqhTBIYhUF3zzEsegtcvQiNzHuhLtjtyDpSNYJ6Nqe'
                b'f4XKKptpUBEnJSXfde13IY1dKL9dLAJr0fMuZNb45oR/Y0IQL/QeTIV5d/C+dMMXk5t+eCqD/a9dYku1'
                b'2lG0cHfgGtwhh0qRyXOsl+FC0KVqAW5ekG3FkDQklkEGVU1XsK4qnoe4n3efA7NGSp/bCdDd1Or+pFQX'
                b'zFGlGve8HSSAQ4Zw/gz1SoKqoqiqqIiKoqPJpJx4jOMuFaJbDmAq9fnsia4tTrm1RVQDpsQZkAlgozDM'
                b'8wsubcjQAXK8EWHPC3nyy6mvr64IOw7WmRcMGrBD3sFmKvfOMrXcpnxLTJfNnIhvCvceuDPe5EnGMt42'
                b'EtiCgtU1gvl8rQEzgIVaVipRQnKUkYkkXIu3e24TGmVRLoHfb85l2+OitcVXWChdpc9kuv4288Cj7HFX'
                b'EjAYswtqwyAYK5NqU4zET0zw6zGoCGff9IjCdJuJ5RAxjBCIqSymwLJABcQEAAZtzp3Ii7XhZS21TWiq'
                b'4fX7+u5r2uPd29zTDbJ55pClgGYlnZmiDddcfj6g+GdGnn1NQ9whNJCO0fb7QVYJ97zzrTOhvRy30FiA'
                b'K+8R6zBvhQQ0HiaGU9jyqewgQngBB4+BTetEjwuJheit5sqr6AUG9kb1Ytn1dPLC+JZ5GngqA6bJpvQg'
                b'jr7+/nzMxALsKDpYHMBgElDxdNaIOb6AXHQZkdQdRI4m3lm8V0KIEu1ytj0tFMCLfamPLz3A9PSJwWS2'
                b'AZJksMG5umoYNtfWkC+VkWsOBMAX8ggLBrB9vue7XzkF0pb2/a9n7emlPZjMSa3noYGHJPP5bfxYGr2V'
                b'Hyeph4fN3Ew2bGQKPFRK++/aTLUCrFaim89TTUAwCpmbK5poB/bSchHQlPjVcZidXquXLly5cuXLly5c'
                b'uYaMcudc6kZF06dOnTp0qHWNs+NneVSK0jNBThmf5526SSUTNIzA4FHR0fAqOBzb6pwddg5x9WPLzT9t'
                b'fYPLP61v0LTmXvAv8jV+xtuNebH998vu8LcXW5226u8e83O32t7vsK+vqCgo6FddddddewXXXXX06666'
                b'6666666666666666667169evXr169evXr169etQ5eTgQHiEGHhoUmnl0up/5Xt4APuLOp6eosxQsqOjo'
                b'/ImmqowYZp/fn5/4IYZ+OXnOFrkssss7wemrPMEGORgdrrCjsWOpkjjkPO5zGtgSIHSPqvSd4d4erPuK'
                b'WcjtSO4qb07Mc+r2kY4d19tQ8HcYbZZA+yW1XeWtJfdf50yw1ufHz9ravce3t2ePkciLj4+P7yrHVizZ'
                b'MlV/xM2bW09PSbeuWq0GrmhXHYYk+fIqvcl37tpCgG9i+R9hiDe9UKLAR4DSAshFhAQYApANhCTi4sgZ'
                b'RLkzWnQBTiI/YYZdiAPLP5YBLxNRAFe1Chz5XjImnEDMUgpCdm2OvelCYuM/H731nvpo5e+bwxYybVBL'
                b'aKrWoIqiopFkWAqZAEEQ4aGFzl38X+hPWo96oSxZbx87x2SDPwdj/vRLskMZX8EaqM/BkzF2X0UepOv7'
                b'HqujteHpBA3a+CTfXdJk8Yj8Yg3QHQJbPhEGlvLpcHWaBLtkmTzrTVjz5PMEFwYWeoIPl/1HPDQevSgg'
                b'wzBginX/VL035LDS8+HGyp/UkKTo7ge9HfIcXJi7qzPDZV0YxXDdJbjKR+KhaZaiWyciz3E0aVPm/noW'
                b'abhTksHHI1m0R0/Ho0X/Ko8PwCOT8MpkQOUYvzOnnZTyA/561s5eMc93iMrRdwa/kIw5yEn7SnvGc5dH'
                b'ccG5O+ZsyOjF2apYm02ctzPGo9cjstnPVo5I2O6RvTaS5pUfuvK0alz3aFYfTTnJYgMpAbntv0SIZ/HJ'
                b'eT7p/7iiCDzzCQBVKWRMGCqwQsBk4ysp97gpJYEGUM6QIYiMAUUei0IFlESDUp6rn0aEXuwy763r6Jyz'
                b'Rx9JQa3cLGJqaLOcR5E03JeF3IGLi285aOsR5aWKYOpibnkcNHgv4o8douD4XXWTaQKHG5ZJUNthSQTo'
                b'EfH51mubd26PbI8LQrvfI7fzE9Wjz2ePAoMyOljDO9R0lymjhrNuaXBy6Y7GVin5aMx2Y97IwazK/qj1'
                b'apX01Gr67aY2NkU69G/xMfVYBLDjPI61Hy6og2Xiq/qR8HS9wIAAwZmlS/GfLTJTktgkk9QXZ6KC0+pj'
                b'kK82LYDxkCONyRF0kg06vM4WXLxzsfFPuXqIT2UJ3bDwljBYCCCwFiKxERRhBQBYpDP1qa3Avksbu16+'
                b'E8rohPi4JTPRVNiE8MZvja3yOoo3nXeTncDv6c50SOR0iPHdtSIiidBOS97dCQYZBv0RfYAhiW7Kc+jA'
                b'q2BCBJIRTn7+MHHujAAWTX+F68JkZTIpAlhFCIwFIskIBsMAiirAWQGKEWQnFwHBMmZsCpFJiQAvPUQU'
                b'kiCxJmeopm1//F3JFOFCQmh2ZkQ='
            )
        case '3.3.7':
            b64 = (
                b'QlpoOTFBWSZTWamJu30AHX7//////////////////////////+/3///3///f/////1//4CefaS+jr6qQ'
                b'5SoZFBVXZ28de7j6POOuPk9V9s8D26KAH3O4VEH1z2G93D0Nc2Ad8+db3q7w2826tzjrV2GprqOIesWt'
                b'Xvjg9mUnZCxD09OuvhzHsp270vsopMMkRJqZpNpqeiY1U/BU8U9qn71Kn4lP9CMSe0mTEeoTxTMk9GRq'
                b'np6nlMeQaGp6NNQnkyZMFT9U9T01P1Ieo9qm1Bo009T1MnqA0AaZB6QBkGIyY0RjKaGGSIJiYJtTTCZI'
                b'9FFPZMTRTzRT01MjJ4KeUz1Q9TQNimmj9UGQfqho0GjQAAAA9QNDQBoAA9QAAAAAAAaABoMiA1IU8mmS'
                b'h5T0aaZT1NPIjT0nqA0B6g0NPUAAABoBpoA0AAABoAA9QAAAAAAAAAAAAAAEmlKApkakfpT8lGjyj0J5'
                b'IeoNGmQeoAGgBoyA0NBp6mgBoNAAAAAAAADIAAG1DQaaANAAAAAACJUIPVGqnk2Rkyp6fqm09RPKZRv1'
                b'UGamyg/UaYoPUaeppoD1D1D1PKDah6h6mgNMGUB6mgND1APTU0APUHqAAAAaANAND1DQ0yAzKBEkQRGT'
                b'TUwmCTBMVPyCPU0wm1JPxKe1PKntU2mp5TyaTankh+oT9FPSNH6o9k1QGmT1DT1PU9QPUGgANAGgAA0A'
                b'AAaAaAAAGmn36II5iP/2yII4Yb1abdLSV19lO/lr3TZvTsegcCO35noCCFxvwOOYX3iCM+eSSZx3Eyim'
                b'qvHZbkzs/BSSBdWidjmEOzOUE6AToBOgE6oJ0KHQIdCB0AHQr0C9CPQD0KdAnQh0AdC9A9CdALDYMdFd'
                b'zpIDxIDpIF8OIHdfS1NXdbvW32/4HO9o5/T4PD4vG6JjN1OpakGRoYytr78M+4y+fMBBFb0e7JAglaVl'
                b'SNPIYVBibtQ468pQmye6ULV4FCfTqG+IVzdhArjAIYFZgFhgRwVEBhgUhgEhgQmRMYCfb9H54/NUCfOg'
                b'JURIoRUUOae727du3bt27du/2ejh6vX8L8L3eTNYZjDNOrRoCc00s2TcIbhDuwM4hyInMCRE5jmKQQS5'
                b'6cTPPg7XjoPf2Ht4KoIARJIiAAIhpKiq+rSyVEHrKitFLbbOO1S47aDuKene7JprreD3fCWg8ngIiCPT'
                b'XhlwsUcKr6AdKwjUmHIA7MhOOQ3Gzs42c+TRTQppZUJFFYuTjfPt4l8gJ5K9vLPSujGs1wJjetGcztMb'
                b'FEGEREQd+lRZJDSnXHDJCZ2Ec9yulMaTBbQoxXOCheA1BZFBkVkBvEQrJFkigEUgoBFk1UqSQUmuqFQF'
                b'JIKRQkFIskhFhIbCFQRNk6nJTbKk9FJFH0KZlSQ5A2u/a6O0FAeBF4dzfyz4uLJzQARMRTivVgRzFIom'
                b'YJfCrICjmCQN4Ezo9zDgBIKuQJw8fvATdz4s9erVWMxvbVuaMDAgYx3dIJOVQh0uUIVZV9AqygCF25BM'
                b'oQmkFx7QcqjL4MtQVylIucJosjGsNihczgNlya5w2+dTlgro7zXiH4Cveae5qz6+zbt0AYxRgSIonWoO'
                b'vBwRXUxUMqNuASKn8s6pXqmXwNBUZ+w0dYUioX9TCq/FsiKguozNPXXXXsrFARvCMy5RHeixnSLXJs4E'
                b'S9F8CadywJtgAGcFTBETQx5SIiqXlgCC2jLFSCld4kL2JqBN3VaBVCZRBMoiUKBiiVbIjLBkCXEKgqRE'
                b'lgosS1iQypEBbAlggVIqQEhVXjY7MFKyiDSgSIDAHH4FgSyJjCkWQEiJSUIIEZspApIMgMIKgDIDNZOi'
                b'O5a10u5dd2HYQDTJNGjTcRuGRunLNOUzZjHHCsL6DQaDRfAlC780i7GNrBbhpG6MpahQO6oWB4bVBEsA'
                b'Upg7wJV0kBgkCQThoSkKUKQkKAi3ZQ2BLJVhaShQhYWDFEoQstpSyBUlaaKsCX23uOHDbEElwl9mrTv4'
                b'ZAkyDgz96XvgCVSjIgLQJRSAFAmoEsWsoVYElrCFVJSBYEtZkCyuclrXBKurLQoWwJVpCyNVYEqwMtKU'
                b'soUUJKEJYSyGmtmrDXcAKxAyQKspiS4AHEwSllhiSYMYC3BJcRMUwjaxJKBhSTTZSrSShJUM9VurETcy'
                b'rKBniAxkZaS1YthaJQStjUpCkPCgG3DmshhFFFYTq+JQoI7pAHaaaF1cgl17tNPi85n6zTZ00gjOGdBC'
                b'SRGKoAhBDZuSjKyxH/FkQQGGCgq7euue8u+LAvoWHEi8nl5GTl5tlofoPo8/KHIqcsnzoUoeIwFMIKh2'
                b'vIpEEtIRAUkFRDrQEWEQUHGqEIIVCGaIcwId1ENoIbNA3QBrldeLtkehAaIkXoIaIDQAaJaBaIaAaLQa'
                b'aaDQaoXbt27du3btjGMYxjGY8UscLIIIIINSBc7bbrsNlNc2LDU7Q4xxbKL2F+iiSTAyaSWaaCIVz4Km'
                b'WYFt2tuTvTz33555555556dPFhpYxjGMYxjGMYyWiDFTYrIyubBbKHMF4kjGgAB1QgJFy87eKjbGNqS2'
                b'qmxAS3vu353V+B8f8J6du6+UJIHo0NaDCvO99U921w3Q/yBCIeW/0DsMt8EJfQFUvHDUQjldfMbYgF5o'
                b'3ghQYjEYjEYjETJjAMugZkzYMmYzQFhwttMM3F/wIWFDiYuNyeXj8zKy665zc/RgaXB59AQASNc1Cn/g'
                b'QuFYbKmse/Y7Xief9na4/JlRH46hAPFgMgHSAYJcgp5cRA91AS0+Pq12yhjlQQiD4M6A8A4qolLKlAbg'
                b'JDHC5hG0UbgJVsrInup0JGUCJIUDgops7dXlSMthwlOrKnSjo2mbpTy0FExSTkR4/peNZQuAiOuLxAk+'
                b'JOzo0u5t48MMQTHp0CbLZWAzx+V6GvBNShAE250HKsCvVx+fODv/l7c2v3AJp5Pi/a2w36qGzfBNnAXE'
                b'TpRPwXBQAZiETIkBACAHkad0V8RKhtFOX+FNDefdTHeiODg9T2SjF5rgLG0yU0kgSZ8+Y1LaABFyAP4a'
                b'WKqzXrbX6an+VxdnZ2/fuh2ec6vgeMny9ZEx32yqcmLlUnNy8znZudPZ+hSSlFUVtZ3FZTcq57nlVuXv'
                b'Mx/zMnnWebe2tpu4nGtM7E7vEz8GxuNC4tsLAiwsHBwsKLhxYcXkRYkXEjQIOLGi41/GhYN+CTCIAr0G'
                b'AFkEcdCCL0Ejj15WGeG9pOPZSjpVnLtsogiXZ1SWUjfawkCrLXFtdxVM0r0xc245p6+NlX0P1G5JIuKw'
                b'IIbNzxCQ+0BAQMhCSB3TogKK281ra7i19fxbCbhTYaa22uiEkAgTxCdL8hxoHNJZUPX8b4vN6+BkgZUA'
                b'H0wMM57zpc3Nzc3Nzc3N1z1/ndHi9ryvY7/VEMZa0RJESREkFJESQEnBClSLBGKRBqNKxVihBAgJEAgJ'
                b'AAgJFWAkFYCRFgJAWAkUYCQRgJEGAkAYCQBgJAT2LA+TBOVXloEPHnzJ9+kALhFcBalInsePQB4hhT9V'
                b'9buIe26VRGK94hsAXryhsLGG66666667SzB57PEwFHZhHRbq4BziQbnys+2atRyVqw6sIjrmNlX1YOEP'
                b'ZwRxsinnK+6TdKX3rUowUZMmTJkybh5555qja7GbY2Njb7GxscLajo6shIyBRAJ3MU9sRU95PZg4oYyh'
                b'HR1hXzu3fpnNzc9VVVVVbbbbbbbbbeU5Tl9eegdsBragQ454HA8RjNAzWBAtwEDkdO1oTTIkxUpi19Bx'
                b'97eiiQlQAtQm0IYUv6OpxM9EHEAO+B5+jlv4K17duuSu/w9/18vS3De2RKU1zyPlfNwMYGALt4oCa4hI'
                b'epfe5/tPL6R4SBxcVqq1VaVe3uNMOBJukKid6l9XYy2WyBQAL8AV6pHVuQ5WtV/f428DhwY8z6WmBjLZ'
                b'KAkVu43Usw6uIWNqhq2xbpg29E2YIIzqYDfLHvKC2nXFZQzrVGtidsFbumj9hHx6pwWTMmooBJ0RUJvC'
                b'wo3AoWwlUw7ONrmACLAy0cuRASHDjLLKcjkRlgg0cs22bErSxIkZbxGwAbpiYkZZBDCSmLMw2CQWUxZ6'
                b'YWQQAGEdXFPIECBZRsRu+ixlkAg3SSBAt4kwyzpcCNtoTIBHeblutZQAiKlRU1IUskB+wyvY3FHTFdk8'
                b'KXc8rFCXTcVWSSWZle55y9YW9SqS2VKlQQXKKgWsCxBikBIrASw32F9HfMO8h5TyJJB3jiS936XTZF2W'
                b'ZXU56kGwlAoOFjmeVAEB6FERvKgtoqlpb7ApUC0tEEKiCEgCEioEme5SIFoiBICBw8WtEgrQDVA6IWBM'
                b'y9kCwJdQ4a6fJNGL1MS3ZlKpfpppppmwX8FKsIRBTfxSCFjL2BwLJAAxIQANcq4FIAVrKFVtosiRA1xW'
                b'ypahCgTAtYEsCXBPa4zcwz46y46rj2ce/x8fHt3+Dbx1xkhx6yujjbb+hEgAUKVQJQJYtYEsCaFdnHxY'
                b'cUxx7Wrum5wTcmugMszRqRIq0CVQJQJiWsCWBL6tV9Uvk1kiQVkBKKoEsIH2GNsZfYcBma5MNCJEWQEs'
                b'VQJj4enTfTNOO2xoZoBICyAlFFAl1c87Zy+LuCFshSKMYCWKbwsCa7AntZ3zl8mskGCMWAlFIUCWBxn4'
                b'mVFX6+WQqlJFD2YqfVGz0C07M+JfHD4ZwYgY4mCAC5kufSzmJc5nPBeY2zbXdxkMfeMzMzMzQIIiQRIg'
                b'iZCURLQJbULiJdAaKNBWiAUACirQVoi0BaKNBGiDQBoqUFKAEPwdzt53OmYQD0ydNcGzsuo24nGPRi2/'
                b'eNSDSjYxjKqqqnlXlU0K6ADbDSCaQTSCaQTSCaQTSCaQTSCaATQCaATeXwt4PCefYifL6Pb3vhz5dl4Q'
                b'OadRDw/K3jrQBrsbtr1v2kJR9Xf3ukA8w9iAldj1fg9uvpvh9s4+MQd8m3c8rg9o3gS4HLv15pzGAgji'
                b'78ghACNbcUyEQyHLjstII1cjTQxt5X3ixi0JI9WclrW5/w1d/lZB6eR5MDlm/kGmbk4r62wvzIE61X9h'
                b'5joERnz5dAYvBRZYtpz6lSYDq6urq62tra2trQDeo+++++++/BBqCo6spJuTuzR3mXDh32lPcKFZWt2F'
                b'dpNxBDpBD0YkTdcFkQ3QzDlJNANR/NfVmA2EwPa23ngeoo0IwrGVwEAE2pWWjIB9iZ/XW9tfhnkWFPN3'
                b'TzPbIlQUkFJBSQUkFJESRUhjSkghQxDeIo0JEagrQsFtC0QCwhASogFAkBKgAUCQEqKtAkBKgrQJASoi'
                b'0CQEqAtAkBKijQJASiQlCCEKwJQghCoEoQQhUVKBICVBSgSAlLq2RE6METna9PyVZrM7Dhw4cJhHCuND'
                b'CjRAoCUBKAlATEBMQExASgJQEoCUBKAlATmsF/Ht8/rWMG+vMG4F3r0nRIyjb4hIySDQtAInO6TEy1Vm'
                b'whRTnZhFMl4xfa3E9iEmfeVPIvcUPkSSRD2JJIB9fJ0HmW5z1JZ8m1Bz+UFFYcP1j59w5/V3x+rdY6PL'
                b'ez4N0zPK+xJvLfY9j0zPrUi6u5N/QHhnFwA8nvOWAfGND2kKXkdeh15r7E1vu86jGZdGdeBCCe+hr0e9'
                b'N7drCWkv0KKMipICirXZIXugvgl4JK4KVEibebWb7iAkAh9AQACXoaaSQMnUKgl0JnZnLy6xM9CSTgop'
                b'TCrN8oWgW1rYb3yxiTZXI5znOp0owUgikLEi1t2/TtmZaIWQcjRMrW6eyauwBhhWl9vZ5EUyIldqg3xw'
                b'e1qxfDZ8vgaIGkdejW59d8PpV8fDuY7FA5YoAHGWm6ay4Jbd5MXN8MsekblcG9yadacp8jeoUtETbE4O'
                b'vCrmPZvadkw1d/GgMssupwhvndNv5X0+nsppDl+E1N4qqqqorqZaYNubVnSdk4cCMzL90nFQHDhi6Xxp'
                b'n2cLWtVV2NPhK2dgYcZIgZORkhDc7EDInhePj3KhOsaboC6+Pj1OSGkLXgfI4egVEPCvjrfUj3A3TJcw'
                b'3MJx7HcsndKfJQXg06UNVg1w3pU23TOQ6ZvDLNODvBDulDTRVBJQFZ00IRCiPJmgFZymiBgAjgxsc1lC'
                b'+awQwcm+dGCFgpDC0dJ4OBqCj3Tg2onOWt50lIDYZcLw1XEG2C+W3IWygJqEDiwMKHc0IcYiz3JbsBqo'
                b'oqB57w06Wm06EwrQkP0EENv3ysgjKGmlYAo2CkcfoYqOTCpzIx1w6IDGzMYN+9wYqJXRAWRABM12WKsT'
                b'Ht1UBHkggrs0NBxnexasQ2IX1SEHlqwZNw6L5XodbasPA+6fiGCJvTVOkbNG7u9J1QyqSdLecqwLSS3O'
                b'Wacq6mdyWoNyIPDpb6qLuOnJCyUdQ0pk6d3S47nK5HjajrIX5APl23N8eawc47ug8l3mjWG3qyM49IJ2'
                b'4CiVEERoNvV6lIByQATTMweZ5uycCcuiRfT1nm9+n6f1/cntfDw8zuDQH6L391DzVD4f2Kh4BDTPrVDf'
                b'UPfoG5D4Sh8FA0T5AB7Vq+YrU9r0BbTwkannqVD5jCu/gbfFOKAqbsCvLE27h8HDknD4EOjOHv88KrSl'
                b'HGQL3QvEVRCyVU6aKp534NGSBSVa11rDxvZkgNzqIAnhK1/0OF4rAQdXreMfHZCEejzVkSOzF/3rpkkA'
                b'SJL58gra/c8F4TdC2spHaw038f59hZ/XgdjW9lN52f+P9f87Tj8i6CoL66OXNOpHZAk0e25fW2HqwUHL'
                b'iqCJIIgAQQgIBJIoJUBCoiNRFWKIDFE1ncCsni4iVIN/KVc7VbzfAWwA1cU4BuUAk9qpgBvV0DTLlW5q'
                b'Y9hYYUo6QRBDUxR6KliBb2G+YZRhh0S0K8Yyzttr+HvOwbIzMzMzMzMyqqqqqqqqqqqqqttttttttttt'
                b'ttttttttttuqEMYxRRRRRRQzMzMzMzMzWbgW6IABcoBYyK/sgJAAC3tyoSZkjabsQJxDJBUQUQCwuWQO'
                b'jt2FpUtInnug5uuuf2qpnVWdFETVwU7iRB5bVVtj40qBsgeJBtD67esljg4KtD1YA/CheXmqIkJCEUd+'
                b'8LDYIFQtEE6sVWoKF4CEvVor9GCJaWioC1ALxD7OLeDeSKSNRaj/AtSnrT5PxufeLgCDnAygP0WfrxdW'
                b'0621MOZmN1GSSALCQFZAFEJBDaaTkqwHMgqV7o9Rh3vo+6eUMiigcnApASHFVu0DpACEYUwhAIBUhAJI'
                b'76dgwaWDSXNQ/qIOrfQYMGC/gdzX8bdy8uEkVGqQ6e096sANiQBHoCQAOagL2cJAuXe46wdaZD/KZWeX'
                b'frOtnNqLmgeod0m+SQ4VDkGO/guPE2ERfixM/PyM8sPb/iq4vHt94D8fTW1FKc1CpUPJijk9NQ9Asig/'
                b'IiJxztT4PbrL8HSVBXfe6q5vS6XQWCfX67/O69jaQyjNPn9NYCZJIogOFeF19+eAv2oqSKgRigSH6qnf'
                b'3J63TuN5eqICI4EETi1yZMSYFQ9glcCz19AzJCEJAk5IAFXS6fPpgxiyA+H43kZv2v3+b6/tx7qXcbHu'
                b'97Rax8/Vrfa3kycG28/wpl0ACCDdgoSCyh2Ccp07C5woFWKgPI1tM1TNKbcv0PJew7eA6m/cFOHRqFdF'
                b'JB3vsqksghqJxcvb9XiH2vQZOTi5OTVteqxtIB6/qMYE8Ra3y/QgL5b4XZaG6qWhWRQcmADnxFN7A6eA'
                b'nPzn4id9hmamoRPcw2+zqBPidqlDxvZoQ+siB1erQB50VD1oq+pFf3sV56I5UQN5EVz93YDemXNRCQAJ'
                b'JJARImxICgCEIE34e1YP3qGhlBKuSQNT/Pnen2pTwIjoggXoIeDus3HFMjQ7rtbBS6ogMDLhqoAFyCmG'
                b'bXcKBA89HPVAA7/raUl+GcnJwTmj4fDH+Kqafe5VOwQXewUARBNWokm5GHGPbMUrxiTtP4aAcDM10Qsg'
                b'fE4v7XauD8A3fy9D+D8PGMGDAYLgfu/b5/icI/78Doy79LNR+X72wAb/g6r8QFjAK4EgSEiFTVU67aGN'
                b'0lgJpup2B8Gwptut6T9F+/fNB2J37njmNb+b6256wvuOiYsEHqdHUG4qqECEOH5cqUOt9n1fF03pjwOJ'
                b'dL8aiMIgn1Ou/Tfv3zE4XpzjbHtN2cjQU0xnLAIorpFEAyiEjMSc4aiAOImuo/BC8fIUZpB5vJHnTU1N'
                b'SX2Ow5B8frNFssnJNj2eMoclAA3Yh7uEqFNZFRQiIJdXUmVEgfd2w/T6TAksz1w8ePN725fqdWrz+kIF'
                b'e5JBEtpSq2koemOu8YBAmqhOJ3w6PpeDtpmZmXw9hOjgDsYGd623dgAfl9BQADOxUSVAJCTdMR/xaHtm'
                b'9RozylhPT8xvJCdtPSHZeN17cAB/UeUOh+5/Epxb7Xm9menp5jQ+b24gqPc7fQ+N0dQbfT4HmXJGjOEm'
                b'OPln9X5N1DyYh+Yc5R8qA+nBd/vl7B7ec8DuwQuuV3/k/fcgYK8z4/lM41FgkeLo+tQ0Lv5HO9j7Mz7L'
                b'jtTFpov/EvOF/68oA63+6cAh82b/6kClUKg95QgyJIMhX0KO7FfopMOfn3b/04LhBdEE+4h/klvg1rx3'
                b'bKetDydWrV536Xy8gANMFZCTVPiFt2yPuYC7m5uWQfzMCABAEuKEKQNLxLWJYh8mBxcXFxbBMWC+OvAn'
                b'RAniuCCbME42gBMoEvgmOCaQEzQTSAmnUMgQxkDxoB3lXbi7RHig+QU80JuEPhgd5fuh7ieoHv398dVA'
                b'Ny9IJ1P5fNYf/MfF69drtdPulwHCdXn02EzzzsAPbghq0V9RnQmedLnopQ0GNAY40itovfvfduAY9uux'
                b'Y06LjnnSq4QRLxL33bOECoPh9i6j/HzwDHPP54p8PBAM4J4Zb6o8BmasXgiIkPucJSlIPABihKYCmEIx'
                b'ebxE6XDX8rPPk7mCJ0/S9b4P3WKjjvQDsTawB3oFQAxcNYZeFOH4bGxqZEWuv22YBznEqAtgN6CaGNKU'
                b'731HS+YuJQg27l0rFLILODatVWJ6JRiV2cisUdI2WVqIZ8USuuoEuzBk1I8CNhjcrm3aaz9l1EeUiBhh'
                b'QCaIppjQJhudT/rnnkPnS1q4YiaIjQhp7yQYAEQXMRjJ4BEUBJ5SoFNH2zm8AVBaPe9A/a6aVJLwEVKU'
                b'NVfd/sMMvu8uzscwQBZr8S8FKe8uAlIoqY0UBSmvuXLFFG2oU8jDD7nFBNEQBL3pBGq0NhcoCZwVGKHQ'
                b'+skss1c3NpKUsRRqq8zWAmKQUH1P5N/d12+yfjya33OK6tv+Q/B93feV23dPk62F5vW1uh7vb5erwrbb'
                b'baqqqooV121EggC8CAq5ttsAtoUrifhirarakrrrrrrrrrirrjWiVRx4eOGN1oiIgQfFqqdG902mmiAR'
                b'nWEAWQRR2S2NYLLLLLLLLLIrLI1omOOPJYRVVUFKUCKUFF55HrXO5Pk06dIJgAcW75dwMcaMPvWkK8f0'
                b'h8E0/h/jZGYEBvu963pY4WZETh4OGWBNE2v29rWKA27bmsL0Aqh37+PYDrRA1RSK6t3VN+/i46000AKn'
                b'lnDjtw1YreKd2f4oimvVrmP22p6UNw3HQqniQVchYCb8/NzHGhwiiBu7m7L6Uy+y+lmNomEADakKkFps'
                b'lOgwQfezpkgws2bEYEG+GdGi5G/AtkLu5A2/wjpg19bvDAS/igQkFHfHNiCnZHoFgGahgACAGjgNYGy2'
                b'hBEX4TjH7lQmRppozmiO/zct8jakIAQOh13jXGaYTU82owXAOo26izGF9/De3TggAkUn9np14s9E/wY5'
                b'S6B05y0A7HbAHf1ltl6rfs2p625pUEEG/w+ebabJKAjK9EiWjOULfSpimznMq1rWpSrwXKqt/EqewXLW'
                b'saOcQeMmGwuOnsOG7bT1Hs7w2b6QWZ6Nuitzbr0Bi6Tew2G5Wzi4uKACgnWggCW69KD3+N9oZXGxScda'
                b'1QtFCH4EhQAiFCVEDHzOkcjbcAD6bwZoEmJvc1wgc9xND6F93CFOgFABKtaagizxmFwlf63zbwGrqSEu'
                b'VCnQegLqNVVVVVV2uwLMs0QHet7iwpfC5C9gS/RgUCYFrWRLHBKBKo8SwJlYxyuCZZYVYEytQJWNAlqx'
                b'soVlSBk3VgGe0AxbJLaSW2EqEWQUgsBzUAzJFhhBYoq1TpsQwO0ttttttttttttttttttttttttttttt'
                b'tttttuXKENsa+84Qd6snE8NNeXpF3ue22q5eXRcQpethgji/QMl73jhlJieLMEBejz9r0uAkITh7ZUts'
                b'O8VQK3RklPseujXqYAJ8phfF9XMhaBCAytKWJtyd5aM4mIZx1MEkgFRaLgJBreeJjiEeittbRAQhyVWm'
                b'k76GZQ4HG19fj6/E17tfOxG+DWizEIoooooooooqjCeCTmTqPJ/34uRUA9x6S/zPW054gJXLJHsFrcsZ'
                b'GQ1803tjg2zDYZIkbNu/HK2C2KZGtz7zf3QBgdWq+y2kAjJIwMfPvgPzf7FKCCvld3zfMy7vwsAR8ueW'
                b'Q8WjzPFrx/vOMfHkgno/Ojv+4wtuPHwKAm2KILzOos7Xg27aqxl+S+bIzGzBe0OVNU5tyvnas5ruiC8Z'
                b'zkW7fbvcBv7yh+cw/aWR9yBAOvjtxq4CIQ2mny+87Xoa5pYB2PX6V3qcW9McjHrLyoC62txOiE3pCvaV'
                b'yQFQPEaahUC4GnCWTqnoI1yVtRak11uYt3fx54YrkzDoT3O3VtQRGHJVbL9QtcAeDcfvfd8Tr5OBrpxz'
                b'waAYR5dFxsTHDCmcycb07XyJIREACT6fuDUrQJJAS+zSJ4ZO2mpMZdGiWFQSdw5+0k3te8gHWnp+not7'
                b'30fD5sOy6cgEXD/lyWLwAQezAVaHM9fmW7QAEvIBqIoOTB0YMVNTaMQBUO55PeHWlz0z5uVlACGH6arA'
                b'Ye4++++uJ9/aiQb0cw4+mw4//HuWFOusuY3AuM/XzdpLxLz4mr5k/rOpp+T4+N7W//rwvL3GD2PhdriQ'
                b'77l+nc4/iZFrlw+l7fX/BqeBqZOpqQaXHpaan29VVRz5LhDxN9S6k1QUFBQNNNNNbDY/7nnr169evd+8'
                b'nZumfTNK97FtcbSx7O6kqXgxtOtrbX2bap2uH3uRVPsP+FvV1nUvOnXWnZgdexrIF5f2fdacHjejvr6D'
                b'f215b5P0cq8yuhb8G6xPLwruBd3fmRciDe3sCBfX3Vd/8AiZlZEX75Wz4rrFt1cmzktKt5PLU65yuXNb'
                b'TTbVr/Akkzu3RxshgW1NK5a9A845BbBT4tyAdOZh1Cw2EQkIAgAeQGBbhnWZMdZnkB+zP+P5HmvrQPqJ'
                b'QJaKEih9TAE+fBC0RCQQ+pio1ECQSRH1Io+CAfuoguvCpXJsuiWiQFAevz1bufN4ujDzZty+kW1Twjkt'
                b'jiARd5ft8ZOl/KuqzddVg7IEEYFlS7oWIm4DJhxJdiVnl1UjR3HRddJAKfLxmExq+M51X5GqXP3+9v5n'
                b'Hl8Lc1t4m8tAU1RpZLyx+3sX63vavgevyvezWPzzdg7LJtdNrIhk2g68EjujVaZtr2CwXZ7nHmj9DGVe'
                b'2heuridJMVLRCHSxZ1r99KQvszUoeVNXPfEeL20sZhr+d8KJB8qnKQk5ZI4WgQFSyBe2UutKqR8Tr8A4'
                b'V7Pi5v3tH9MsvLdxL75AMFs48k412OF8rTvqs1UMb3SDmcLK0Hs3t+r90xxA4oXSoilz/6FLiAkT6pVB'
                b'9jk89ZkwiMt1++lRoLlk5l08wmHMO1CAgJlXi6rbS6tVuqYe7HfC61h/2NaF83TuAJIBOsJhZdTASqZx'
                b'PYnTieHlWw8ZQBbAwBBUfoRUTsRRTjxULG9UiCNSKfGih+eChIISILIoMiAzyKF9mCloIbIBtiyD3oMg'
                b'duKgdSIoMggphFEPEiAaoItkQEkQF6eIG/igaObuK1RWRVYR7xYSsgsgsBQFwkrIpFgwJEkJBJAQ1QEB'
                b'kBHTE1QJHVAk1fSoPxv3NILrgKpIiCmcAUNMAFkikiwihFkFILAUBZFJIkgSMhISLKFUDc132OJXrwcd'
                b'+tahZAo3iqhCSE2R+2tQhv8nzrl/i67FlAkgyHs0/1ovWIHhwwSat+hAPly8WR+BVAHXQnJJhztSAkCp'
                b'VgLJA1ENDNjJZws+lLdU3PuJ6OWIGME+0mu2qWhOOPchKKDyO1WxmLCLeKdFikDnudsFLh3ooGEEghF2'
                b'IhApAeiu4Labzt3BMuTKebM3nniO59LzGoikWC7be0DBikogsRgxjuOH5bg5SQy/Mpvnpi2RJQQReX1t'
                b'gJCCipGQEiicif/F3JFOFCQqYm7fQA=='
            )
        case _:
            raise ValueError()
    with open(file, 'wb') as f:
        f.write(
            bz2.decompress(
                base64.decodebytes(
                    b64
                )
            )
        )
