#
# THOR Direction — LONG / SHORT / FLAT, TEXT
#
# Column settings:  Aggregation = 5 min   |   Extended Hours = OFF
#
# Reads the sign of the same three inputs the score measures. FLAT means
# they disagree: volume may be heavy, but VWAP side, momentum and range
# position are not pointing the same way, so there is no side to take.
#
# Do not sort by this column. Sort by THOR Auction Score.
#
# STATUS: not compiled against thinkorswim. See README verification steps.

def momBars    = 6;
def newSession = GetDay() != GetDay()[1];

def cumVol = CompoundValue(1, if newSession then volume else cumVol[1] + volume, volume);
def tpv    = (high + low + close) / 3 * volume;
def cumPV  = CompoundValue(1, if newSession then tpv else cumPV[1] + tpv, tpv);
def sessVwap = if cumVol > 0 then cumPV / cumVol else Double.NaN;

def sessHigh = CompoundValue(1, if newSession then high else Max(sessHigh[1], high), high);
def sessLow  = CompoundValue(1, if newSession then low  else Min(sessLow[1],  low),  low);

def vwapPct  = if sessVwap > 0 then (close - sessVwap) / sessVwap * 100 else Double.NaN;
def momPct   = if close[momBars] > 0 then (close - close[momBars]) / close[momBars] * 100 else Double.NaN;
def rangePos = if sessHigh > sessLow then (close - sessLow) / (sessHigh - sessLow) else 0.5;

def bullAgree = vwapPct > 0 and momPct > 0 and rangePos >= 0.6;
def bearAgree = vwapPct < 0 and momPct < 0 and rangePos <= 0.4;

AddLabel(yes, if bullAgree then "LONG" else if bearAgree then "SHORT" else "FLAT", Color.BLACK);

AssignBackgroundColor(
    if bullAgree then Color.GREEN
    else if bearAgree then Color.RED
    else Color.LIGHT_GRAY);
