// Common UN/LOCODEs seen in AIS destination fields -> friendly port names.
const PORTS = {
  NLRTM: 'Rotterdam', NLAMS: 'Amsterdam', NLVLI: 'Vlissingen', BEANR: 'Antwerp', BEZEE: 'Zeebrugge',
  DEHAM: 'Hamburg', DEBRV: 'Bremerhaven', DEWVN: 'Wilhelmshaven', GBFXT: 'Felixstowe',
  GBLGP: 'London Gateway', GBLON: 'London', GBSOU: 'Southampton', GBDVR: 'Dover', GBTIL: 'Tilbury',
  GBIMM: 'Immingham', FRLEH: 'Le Havre', FRDKK: 'Dunkirk', FRCQF: 'Calais', FRMRS: 'Marseille',
  ESALG: 'Algeciras', ESVLC: 'Valencia', ESBCN: 'Barcelona', ESTAR: 'Tarragona', GIGIB: 'Gibraltar',
  MATNG: 'Tangier', MAPTM: 'Tanger Med', MACAS: 'Casablanca', PTSIE: 'Sines', PTLIS: 'Lisbon',
  ITGOA: 'Genoa', ITGIT: 'Gioia Tauro', ITSPE: 'La Spezia', ITTRS: 'Trieste', GRPIR: 'Piraeus',
  TRIST: 'Istanbul', TRAMB: 'Ambarli', TRMER: 'Mersin', TRIZM: 'Izmir', EGPSD: 'Port Said',
  EGSUZ: 'Suez', EGALY: 'Alexandria', EGSOK: 'Sokhna', SAJED: 'Jeddah', AEJEA: 'Jebel Ali',
  AEAUH: 'Abu Dhabi', AEKLF: 'Khor Fakkan', OMSLL: 'Salalah', OMSOH: 'Sohar', INNSA: 'Nhava Sheva',
  INBOM: 'Mumbai', INMUN: 'Mundra', LKCMB: 'Colombo', SGSIN: 'Singapore', MYPKG: 'Port Klang',
  MYTPP: 'Tanjung Pelepas', IDJKT: 'Jakarta', IDBTM: 'Batam', THLCH: 'Laem Chabang',
  VNSGN: 'Ho Chi Minh City', VNHPH: 'Haiphong', CNSHA: 'Shanghai', CNNGB: 'Ningbo',
  CNSZX: 'Shenzhen', CNYTN: 'Yantian', CNTAO: 'Qingdao', CNTSN: 'Tianjin', CNXMN: 'Xiamen',
  CNCAN: 'Guangzhou', HKHKG: 'Hong Kong', MOMFM: 'Macau', TWKHH: 'Kaohsiung', TWKEL: 'Keelung',
  TWTXG: 'Taichung', KRPUS: 'Busan', KRINC: 'Incheon', JPTYO: 'Tokyo', JPYOK: 'Yokohama',
  JPCHB: 'Chiba', JPKWS: 'Kawasaki', JPNGO: 'Nagoya', JPUKB: 'Kobe', JPOSA: 'Osaka',
  USLAX: 'Los Angeles', USLGB: 'Long Beach', USOAK: 'Oakland', USSEA: 'Seattle', USTIW: 'Tacoma',
  USNYC: 'New York', USSAV: 'Savannah', USHOU: 'Houston', USMIA: 'Miami', USNOL: 'New Orleans',
  CAVAN: 'Vancouver', CANAN: 'Nanaimo', CAVIC: 'Victoria', CAPRR: 'Prince Rupert',
  CADEL: 'Delta', CAMTR: 'Montréal', CAHAL: 'Halifax', MXZLO: 'Manzanillo', MXLZC: 'Lázaro Cárdenas',
  PABLB: 'Balboa', PACTB: 'Cristóbal', PAONX: 'Colón', PAMIT: 'Manzanillo (PA)', PAPAC: 'Panama',
  COCTG: 'Cartagena', CLVAP: 'Valparaíso', CLSAI: 'San Antonio', PECLL: 'Callao',
  BRSSZ: 'Santos', BRRIG: 'Rio Grande', ARBUE: 'Buenos Aires', ZADUR: 'Durban', ZACPT: 'Cape Town',
  RUNVS: 'Novorossiysk', RULED: 'St Petersburg', UAODS: 'Odesa', ROCND: 'Constanța',
  GEBUS: 'Batumi', GEPTI: 'Poti', BGVAR: 'Varna', NOOSL: 'Oslo', NOBGO: 'Bergen',
  SEGOT: 'Gothenburg', SESTO: 'Stockholm', DKAAR: 'Aarhus', DKCPH: 'Copenhagen', PLGDN: 'Gdańsk',
  FIHEL: 'Helsinki', EETLL: 'Tallinn', AUSYD: 'Sydney', AUMEL: 'Melbourne', AUBNE: 'Brisbane',
  NZAKL: 'Auckland',
};

function titleCase(s) {
  // Keep 1-2 letter codes like "BC" or "NY" in caps.
  return s.split(' ').map((w) => (w.length <= 2 ? w.toUpperCase()
    : w.toLowerCase().replace(/(^|[\-/(])(\p{L})/gu, (_, p, c) => p + c.toUpperCase()))).join(' ');
}

// Returns { name, code } for display; code is the raw LOCODE when one was recognised.
export function portName(dest) {
  if (!dest) return null;
  const last = dest.split(/>|=>|->/).pop().trim();
  const compact = last.toUpperCase().replace(/[^A-Z]/g, '');
  if (compact.length === 5 && PORTS[compact]) {
    return { name: PORTS[compact], code: `${compact.slice(0, 2)} ${compact.slice(2)}` };
  }
  if (/^FOR ORDERS?$/i.test(last)) return { name: 'For orders', code: null };
  // "JP CHB DEZU A": a LOCODE followed by a berth or terminal name.
  const m = last.toUpperCase().match(/^([A-Z]{2})\s?([A-Z]{3})\b\s*(.*)$/);
  if (m) {
    const port = PORTS[m[1] + m[2]];
    const rest = m[3] ? titleCase(m[3]) : '';
    if (port) return { name: rest ? `${port} · ${rest}` : port, code: `${m[1]} ${m[2]}` };
    return { name: last.toUpperCase(), code: null }; // unknown code: keep it as typed
  }
  return { name: titleCase(last), code: null };
}
