# _Sharly Chess_ - Remote access over the internet

This document describes how the screens of a local _Sharly Chess_ server can be reached from
the internet, and the reasoning behind the way it is built.

- [View the network documentation](network.md)
- [View the authorized actions by access level](access-levels-actions.md)

## The problem

A _Sharly Chess_ server runs on an arbiter's laptop and serves the venue's local network.
That works well for the boards and the display screens, which are in the room. It works badly
for an arbiter holding a telephone: joining the venue's private network usually means losing
mobile data, and many venues have no usable network at all.

The screen that matters most here is the administration tab, where results and illegal moves
are entered. Making that reachable from a telephone on mobile data is the whole point of the
feature; letting the public follow the event is a welcome consequence rather than the aim.

## Why a tunnel

The laptop has no public address. Nothing on the internet can open a connection to it: it sits
behind a router doing network address translation, usually behind a venue firewall as well,
and its address changes from one venue to the next.

The only connection that can exist is one the laptop makes itself, outward, and then holds
open. Everything else follows from that. The laptop opens an SSH connection to a relay on the
internet and asks it to forward a hostname back down that connection. A telephone then talks
to the relay, and the relay passes the request along the connection the laptop is already
holding.

```
  telephone ──── https ────► relay ──── the connection the laptop opened ────► laptop
```

The relay is an [sish](https://github.com/antoniomika/sish) server. The application speaks to
it with `paramiko`, so no additional program has to be installed alongside _Sharly Chess_.

## What leaves the computer

The tunnel carries the screens themselves, which is to say the same pages the local network
already serves.

Separately, and only so that its owner can tell one computer from another in their own
account, the application sends the site **one thing: this computer's own name**. Nothing about
the events reaches the site —
no titles, no dates, no players, no pairings, no results. Those travel down the tunnel to
whoever opened the page, exactly as they travel across the venue's network today.

A tunnel reaches the **server**, not an event, so the server serves everything on it. Being
reachable is one decision for the computer rather than one per event: a URL that named one
event would still reach all the others.

An event does not have to be published on the results site to be reachable. The two are
unrelated.

The URL is not guessable and is listed nowhere. It is not secret, though: certificates are
published to public logs that are watched, so a newly reachable server is found and probed by
strangers within minutes of coming up. That is why the screens which matter ask for a password,
and why repeated attempts are slowed down — the URL being obscure was never what was
protecting them.

## The two listeners

This is the part to understand before anything else.

The application serves the local network on its usual port. When remote access is running, it
binds a **second listener, on the loopback address only**. The tunnel client connects to that
second listener; nothing else can, because nothing outside the computer can reach the loopback
address.

A request that arrives through the tunnel therefore comes from the loopback address, which is
also where the arbiter's own browser comes from. The address cannot tell them apart. The
**listener it arrived on** can, and that is set by the server when it accepts the connection,
so a caller cannot claim to have arrived on a different one.

```python
def request_is_tunnelled(scope: Any) -> bool:
    tunnel_port: int | None = SharlyChessConfig().web_tunnel_port
    if tunnel_port is None:
        return False
    server: tuple[str, int | None] | None = scope.get('server')
    return server is not None and server[1] == tunnel_port
```

This matters because a request from the loopback address is treated as the person sitting at
the computer, and is granted administrator access without logging in. That is right for the
browser the application opens on its own window, and catastrophic for a telephone on the far
side of the world. Everything arriving through the tunnel is held to the ordinary rules
instead: a session, a password, and the access level that account has been given.

Sessions opened from the internet are also given their own terms — they are kept for a day of
play rather than indefinitely, so that a telephone left in a pocket does not hold the event
open for a fortnight.

## Words

Pinned here because the same thing has too many plausible names, and using two of them for one
thing is how this gets confusing.

| Word | Means | Example | Chosen by |
|---|---|---|---|
| **URL** | the web address this server answers on | `https://eu2iyzm-yzb1phq.live.sharly-chess.com` | the site, at random |
| **computer** | the laptop the arbiter is working from | — | — |
| **name** | a caption shown beside the URL in the account list on the site | `timothys-mac-studio-1.home` | taken from the computer |

The arbiter sees the URL; the name only ever appears on the site. The two below are rows on the site, never words
in the interface, and exist only because the site keeps many of each for one account:

| Row | Answers | Held as |
|---|---|---|
| `RemoteServer` | *which URL?* | the hostname, and the username the relay knows it by |
| `RemoteInstall` | *which computer?* | the public half of a key pair |

**On one laptop there is exactly one of each**, always. They are created together in the
configuration file, carried together, and copied forward together when the application is
upgraded. Nobody using the application can ever have two of one and one of the other.

They are separate rows on the site because of two things an arbiter may ask for, each of which
would destroy the other if the two shared a row:

- **New computer, same URL.** The laptop dies and the configuration is restored onto a
  replacement. A different computer, the same URL, so the QR codes printed that morning keep
  working.
- **New URL, same computer.** The next tournament wants its own web address, so the codes
  printed for the last one stop reaching anything.

A third thing, the **lease**, says which computer may answer on which URL *at this moment*. It
runs for five minutes and is renewed every sixty seconds, which is what lets a replacement take
a URL over without anybody having to intervene.

### What the identifier is, and is not

`remote_uniq_id` is written into the configuration file the first time remote access is turned
on, and kept. It **says which URL is meant, and never that this computer may have it**: an
identifier that travels in every request is not a credential. The site checks the account, and
refuses a URL issued to another — `403 not_owned`, raised here as `ServerNotOursError` and
treated like being disowned rather than like a busy lease, because retrying will never help.

The private half of the key never leaves the computer. Only the public half is sent, once, when
it is registered. **Registering again does not undo a revocation**: a lost laptop still holds
its key, so one that could reinstate itself by presenting it would not have been disowned by
anything.

## The life of a tunnel

1. **Registration**, once per computer. The application generates a key pair and sends the
   public half to the site, which returns an identifier for it.
2. **Opening.** The application asks the site to open remote access for this computer. It
   is told the hostname, where the relay is, what host key the relay should present, which
   username to connect as, which subdomain to request, and a nonce.
3. **Connecting.** The application opens the SSH connection, checks the relay against the host
   key it was given rather than trusting whatever answers, and requests the forward.
4. **Serving.** The relay asks the control plane whether that key may answer on that URL. Only
   then does traffic flow.
5. **Heartbeat.** The application renews the lease every 60 seconds, comfortably inside the
   five-minute lease so that a missed one is survivable. A new nonce is issued each time. The
   heartbeat goes straight to the control plane, not through the tunnel, so it goes on being
   answered while the tunnel itself is reconnecting.
6. **Closing.** The application gives the lease up. The URL is kept, ready for the next time
   this computer is turned on.

If the laptop closes mid-tournament, the heartbeat stops and the lease is released without
anybody having to intervene, so a replacement can take the URL over.

### Proving the URL still reaches this computer

The application answers a request at `/.well-known/sharly-chess-instance` with its identifier
and its current nonce. The site can therefore ask a URL who is behind it, and tell the
difference between a tunnel that has simply dropped and one now reaching something else.

A dropped tunnel is **not** silence: the relay is still standing and answers 502 for a hostname
whose computer it has momentarily lost. The control plane treats any status of 500 or above as
being out of reach rather than as an answer, for exactly that reason — read as an answer, a few
seconds of venue WiFi would release the lease of a server that was already reconnecting.

## Signing in

The arbiter signs in once on the laptop they are working from, and everything served from it is
opened under that account. The exchange is the authorization code flow with PKCE, so no secret
has to be kept on a computer anyone can open, and it finishes in a browser at this server's own
local address — reached the same way the arbiter reached it, so a laptop on a venue network needs
nothing opened or forwarded.

`remote-access:write` is an **account scope**. The consent page asks for no event, the redirect
carries no `event_id`, and nothing in the flow needs one: what is served is a laptop, and the
events on it usually correspond to nothing on the site at all.

The proof of an exchange under way is kept in memory only. It is worth nothing once used, and a
server restarted mid-sign-in starts again rather than honouring something it cannot vouch for.

## What the control plane's refusals mean

The `error` field of the body is the stable thing; the status is only how it arrived. Every
named refusal is **final** — the session stops and the arbiter is told — and so is one this
version cannot name, because going on asking would say nothing to anybody while getting
nowhere, and would hold a URL that is about to be given away.

| Code | Means | Then |
|---|---|---|
| `conflict` (409) | another computer holds the lease | offer to take it over (`take_over: true`) |
| `unknown_install` (403) | this computer has been disowned, or was never registered | say so. Registering the same key again is refused, so there is nothing to retry. It can arrive from the heartbeat mid-session, not only from `open` |
| `not_owned` (403) | the URL belongs to another account | say so; signing in as that account is the only way through |
| `blocked` (403) | the URL has been taken out of service | say so |
| `limit_reached` (403) | the account holds as many URLs as it may | say so |
| `unavailable` (503) | the site has no relay to offer | **wait and try again** |
| — (401) | the token is gone, revoked from the website | sign in again |
| anything else | unknown to this version | stop, and show what the site said (`error_description`, or the code) |

**Two things are waited through rather than acted on**, because both mend themselves and the
lease outlives several heartbeats: a control plane that could not be reached at all, and
`unavailable`. A request that never got an answer carries no code, so it is not a refusal —
treating it as one would take the screens off the internet over a venue network that was about
to come back.

### Telling the arbiter

A refusal arrives while the arbiter is working in the browser, not while they are looking at
the application window, so it is said in three places:

1. **The log**, always — `gui_logger` pipes the logger into the window's log pane.
2. **The Networks tab**, as a line under the heading, which is what someone sees when they go
   looking for the URL and find it gone.
3. **A dialog**, but only when the session ended *without being asked to*. Interrupting is
   right here: remote access is down and will not come back on its own, and the alternative is
   the arbiter finding out when somebody telephones to say the URL is dead. It is shown
   once per reason, and never for a stop they asked for — the button changing under their hand
   says that already.

The dialog says the screens are still served on the local network, because they are, and an
arbiter reading that the internet access has stopped should not have to wonder.

## Where the relay is

The relay's address, port and host key are sent with each grant rather than built into the
application. Moving the relay — to another host, another provider, or a second one alongside —
is then a change to the control plane's configuration, which machines pick up the next time
they connect. It does not require a release that has to reach every laptop between tournaments.

## Configuration

| Key | Meaning |
|---|---|
| `web_host`, `web_ports` | the listener the local network uses |
| `web_tunnel_host` | the loopback address the second listener binds to |
| `web_tunnel_ports` | pins the second listener to a port; left empty, the system chooses one |

The tunnel port is an internal detail. Nothing outside the process refers to it: the relay
opens a channel back down the connection the application already holds, and the address it
then dials is local. Asking the system for a port rather than choosing one means the bind
itself reserves it, and the port is read back from the socket that is serving on it.

## Files

| File | Holds |
|---|---|
| `src/web/tunnel.py` | recognising a tunnelled request, and the terms of a remote session |
| `src/web/tunnel_client.py` | the `RemoteTunnel` interface and its `sish` implementation |
| `src/web/remote_access.py` | what a public hostname answers when asked who it is |
| `src/web/remote_access_account.py` | the account remote access is opened under, and its tokens |
| `src/web/remote_access_api.py` | the four exchanges with the control plane |
| `src/web/remote_access_session.py` | one server, served: grant, tunnel and heartbeat kept in step |
| `src/web/remote_access_manager.py` | whether this server is reachable, and putting it back after a restart |
| `src/web/login_throttle.py` | slowing down repeated password attempts |
| `src/web/server_engine.py` | binding both listeners |
| `src/data/access_levels/client.py` | deciding what a request is allowed to do |

## Guarding the login

Exposing a login form to the internet invites people to try passwords against it. Attempts are
counted per account and per calling host, and refused for a period that doubles as they
continue, so that guessing becomes impractical long before it becomes productive. Accounts are
never confirmed or denied to exist by the error shown.

**Which host.** A tunnelled request reaches the server from the tunnel client on this computer,
so the caller is named by `X-Forwarded-For` instead — and by its **last** entry, not its first.
A forwarding header is appended to, so everything before the final entry was written upstream
of the relay, which at the public end of a tunnel means the caller. Counting the first entry
would let a caller rename itself on every attempt and so never be counted at all.

## Losing the network for a moment

Every part of this has to survive a venue network that drops, because they do, and the failure
to avoid is one that needs an arbiter to notice and fix something mid-round.

| What drops | What must not happen |
|---|---|
| The SSH connection | `SishTunnel` reopens it on its own, backing off to a minute. Its status reads `RECONNECTING` rather than `STOPPED`, so the window does not say the screens have gone while they are coming back |
| A heartbeat | The lease outlives several, so one that could not be sent is logged and the next is tried. Only being *told* the lease is gone stops the session |
| The token renewal | Being unable to ask is not a refusal. The refresh token is kept and the attempt repeated; discarding it would end remote access for the day and send the arbiter back to a browser |
| The control plane's own check | A 502 from the relay means the tunnel is down, not that the hostname is serving something else. The lease is left alone |
