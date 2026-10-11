// The bank's statement and debt services of the final case (service contract of 1 October 2026).
// Every answer is looked up in the bank's own test data and returned as it is, status code included.
// Nothing is computed and nothing is remembered: a week change answers what the data says and
// changes no later answer.
//
//   cards.list             by data.customerNo
//   cards.balance          by data.cardNumber, the masked number exactly as cards.list gave it
//   statement.week.get     by data.cardNumber
//   statement.week.decide  by data.cardNumber, then data.newStatementWeek
//   statement.week.change  by data.cardNumber, then data.newStatementWeek
//   contact.email.get      by data.customerNo
//   statement.pdf.send     by data.customerNo
//
// Token, headers, the call object, aiFlow and the fields that are no lookup key are not checked,
// as in the bank's test environment. A lookup key that is missing or empty is a 400.

import customers from './statement-data.js';

const ORIGIN = 'ivr-gateway-test:ivr-channel-v0';
const NOT_FOUND = 'com.freyabank.ivrgateway.ivrchannel.rest.exception.NotFoundException';

function failure(status, code, message, type, rootCause, guid) {
  return { status, body: { result: { guid, returnCode: code, messageText: message, code, message, type, details: { guid, rootCause, errorOrigin: ORIGIN } } } };
}
const invalid = (message) => failure(400, 'INVALID_ARGUMENTS_ERROR', message, 'ERROR', 'InvalidArgumentsException', 'f0e1d2c3b4a5968778695a4b3c2d0400');
const missing = {
  'cards.list': () => failure(404, 'FB_IVR_CHANNEL_102', 'Müşteriye ait geçerli kart bilgisi bulunamadı.', 'WARNING', NOT_FOUND, 'f0e1d2c3b4a5968778695a4b3c2d0102'),
  'cards.balance': () => failure(404, 'FB_IVR_CHANNEL_120', 'Kart bakiye servisi hatası: kart bulunamadı', 'WARNING', NOT_FOUND, 'f0e1d2c3b4a5968778695a4b3c2d0120'),
  'statement.week.get': () => failure(404, 'FB_IVR_CHANNEL_121', 'Hesap kesim servisi hatası: kart bulunamadı', 'WARNING', NOT_FOUND, 'f0e1d2c3b4a5968778695a4b3c2d0121'),
  'statement.week.decide': () => invalid('invalid card number or statement week'),
  'statement.week.change': () => invalid('invalid card number or statement week'),
  'contact.email.get': () => invalid('invalid customer number'),
  'statement.pdf.send': () => failure(404, 'FB_IVR_CHANNEL_107', 'Pdf dokümanı bulunamadı', 'WARNING', NOT_FOUND, 'f0e1d2c3b4a5968778695a4b3c2d0107'),
};

// The card services carry no customer number: a masked card number is unique in the test data.
const byCard = {};
for (const services of Object.values(customers)) {
  for (const service of ['cards.balance', 'statement.week.get', 'statement.week.decide', 'statement.week.change']) {
    byCard[service] = byCard[service] || {};
    for (const [card, entry] of Object.entries(services[service] || {})) byCard[service][card] = entry;
  }
}

const text = (value) => (value === undefined || value === null ? '' : String(value).trim());
// 3, "3" and "03" are the same week.
const week = (value) => (/^\d+$/.test(text(value)) ? String(Number(text(value))) : text(value));

export const services = Object.keys(missing);

// {status, body, delaySeconds} for one request body.
export function answer(service, request) {
  const data = request && typeof request.data === 'object' && request.data !== null && !Array.isArray(request.data) ? request.data : null;
  if (!data) return invalid('data cannot be empty');
  let entry;
  if (service === 'cards.list' || service === 'contact.email.get' || service === 'statement.pdf.send') {
    const customer = text(data.customerNo);
    if (!customer) return invalid('customer number cannot be empty');
    if (service === 'contact.email.get' && !text(data.intAddressInfoType)) return invalid('intAddressInfoType cannot be empty');
    entry = Object.hasOwn(customers, customer) ? customers[customer][service] : undefined;
  } else {
    const card = text(data.cardNumber);
    if (!card) return invalid('card number cannot be empty');
    entry = Object.hasOwn(byCard[service], card) ? byCard[service][card] : undefined;
    if (service === 'statement.week.decide' || service === 'statement.week.change') {
      const wanted = week(data.newStatementWeek);
      if (!wanted) return invalid('newStatementWeek cannot be empty');
      entry = entry && Object.hasOwn(entry, wanted) ? entry[wanted] : undefined;
    }
  }
  if (!entry || typeof entry.http !== 'number') return missing[service]();
  return { status: entry.http, body: entry.response, delaySeconds: entry.delaySeconds || 0 };
}
