/**
 * CS2 Game Coordinator — получение профиля игрока.
 *
 * Логинится в Steam, подключается к CS2 GC, запрашивает профиль.
 * Возвращает JSON в stdout: rank, level, xp, vac_banned, penalty, wins.
 *
 * Использование:
 *   node fetch_profile.js <login> <password> [shared_secret] [target_steamid64]
 */

const SteamUser = require('steam-user');
const CS2 = require('node-cs2');
const SteamID = require('steamid');
const SteamTotp = require('steam-totp');

const args = process.argv.slice(2);
if (args.length < 2) {
  console.log(JSON.stringify({ error: 'Usage: node fetch_profile.js <login> <password> [shared_secret] [target_steamid64]' }));
  process.exit(1);
}

const [login, password, sharedSecret, targetSteamId] = args;
const TIMEOUT_MS = 30000;

const client = new SteamUser();
const cs2 = new CS2(client);

let resolved = false;

function output(data) {
  if (resolved) return;
  resolved = true;
  console.log(JSON.stringify(data));
  setTimeout(() => process.exit(0), 500);
}

function fail(msg) {
  if (resolved) return;
  resolved = true;
  console.log(JSON.stringify({ error: String(msg) }));
  setTimeout(() => process.exit(1), 500);
}

setTimeout(() => fail('Timeout: 30 сек'), TIMEOUT_MS);

// Логин
const loginOpts = {
  accountName: login,
  password: password,
  logonID: Math.floor(Math.random() * 2147483647),
};

if (sharedSecret && sharedSecret !== 'null' && sharedSecret !== '') {
  loginOpts.twoFactorCode = SteamTotp.generateAuthCode(sharedSecret);
}

client.logOn(loginOpts);

client.on('error', (err) => {
  fail(`Steam login error: ${err.message}`);
});

client.on('loggedOn', () => {
  process.stderr.write(`[GC] Logged in as ${client.steamID}\n`);
  client.gamesPlayed([730]);
});

cs2.on('connectedToGC', async () => {
  process.stderr.write(`[GC] Connected to CS2 GC\n`);

  try {
    let steamId;
    if (targetSteamId && targetSteamId !== 'null' && targetSteamId !== '') {
      steamId = new SteamID(targetSteamId);
    } else {
      steamId = client.steamID;
    }

    process.stderr.write(`[GC] Requesting profile for ${steamId}\n`);

    const raw = await cs2.requestPlayersProfile(steamId);
    process.stderr.write(`[GC] Raw response keys: ${JSON.stringify(Object.keys(raw || {}))}\n`);

    // Ответ может быть в разных форматах:
    // 1) { account_profiles: [{ vac_banned, player_level, ... }] }
    // 2) Напрямую { vac_banned, player_level, ... }
    // 3) Вложенный { request_id, account_profiles: [...] }

    let p = null;

    if (raw && raw.account_profiles && raw.account_profiles.length > 0) {
      p = raw.account_profiles[0];
    } else if (raw && (raw.player_level !== undefined || raw.vac_banned !== undefined || raw.ranking)) {
      p = raw;
    }

    if (!p) {
      // Дампим весь ответ для диагностики
      process.stderr.write(`[GC] Full response: ${JSON.stringify(raw).substring(0, 500)}\n`);
      fail('Пустой ответ от GC: ' + JSON.stringify(Object.keys(raw || {})));
      return;
    }

    process.stderr.write(`[GC] Profile keys: ${JSON.stringify(Object.keys(p))}\n`);

    let premierRank = null;
    let mmRank = null;
    let mmWins = null;

    if (p.ranking) {
      mmRank = p.ranking.rank_id || null;
      mmWins = p.ranking.wins || null;
    }

    if (p.rankings && p.rankings.length > 0) {
      for (const r of p.rankings) {
        if (r.rank_type_id === 11) {
          premierRank = r.rank_id || null;
        }
      }
    }

    output({
      account_id: p.account_id || null,
      vac_banned: p.vac_banned || 0,
      penalty_reason: p.penalty_reason || 0,
      penalty_seconds: p.penalty_seconds || 0,
      player_level: p.player_level || null,
      player_cur_xp: p.player_cur_xp || null,
      mm_rank: mmRank,
      mm_wins: mmWins,
      premier_rank: premierRank,
      medals: p.medals || null,
    });
  } catch (err) {
    fail(`GC profile error: ${err.message}`);
  }
});

cs2.on('error', (err) => {
  fail(`CS2 GC error: ${err.message}`);
});
