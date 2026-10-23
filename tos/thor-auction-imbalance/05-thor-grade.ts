#
# THOR Grade — A+ / A / A- / PASS, TEXT
#
# Column settings:  Aggregation = 5 min   |   Extended Hours = OFF
#
# Scoring block is copied verbatim from 04-thor-auction-score.ts.
# Custom quote columns cannot import each other, so each column has to
# carry its own copy. If you retune a threshold, retune it in 04, 05
# and 06 together.
#
# Do not sort the watchlist by this column — text sorts alphabetically,
# which ranks A- above A. Sort by THOR Auction Score instead.
#
# STATUS: not compiled against thinkorswim. See README verification steps.

def barsPerDay = 78;
def momBars    = 6;
def newSession = GetDay() != GetDay()[1];

def cumVol = CompoundValue(1, if newSession then volume else cumVol[1] + volume, volume);
def tpv    = (high + low + close) / 3 * volume;
def cumPV  = CompoundValue(1, if newSession then tpv else cumPV[1] + tpv, tpv);
def sessVwap = if cumVol > 0 then cumPV / cumVol else Double.NaN;

def sessHigh = CompoundValue(1, if newSession then high else Max(sessHigh[1], high), high);
def sessLow  = CompoundValue(1, if newSession then low  else Min(sessLow[1],  low),  low);

def refVol = (cumVol[barsPerDay]     + cumVol[barsPerDay * 2]
            + cumVol[barsPerDay * 3] + cumVol[barsPerDay * 4]
            + cumVol[barsPerDay * 5]) / 5;
def relVol = if refVol > 0 then cumVol / refVol else Double.NaN;

def volPts  = Min(25, Max(0, (relVol - 1.0) / 1.5 * 25));
def vwapPct = if sessVwap > 0 then (close - sessVwap) / sessVwap * 100 else Double.NaN;
def vwapPts = Min(25, AbsValue(vwapPct) / 1.00 * 25);
def momPct  = if close[momBars] > 0 then (close - close[momBars]) / close[momBars] * 100 else Double.NaN;
def momPts  = Min(25, AbsValue(momPct) / 1.50 * 25);

def rangePos  = if sessHigh > sessLow then (close - sessLow) / (sessHigh - sessLow) else 0.5;
def bullAgree = vwapPct > 0 and momPct > 0 and rangePos >= 0.6;
def bearAgree = vwapPct < 0 and momPct < 0 and rangePos <= 0.4;
def alignPts  = if bullAgree or bearAgree then 25 else 0;

def score = volPts + vwapPts + momPts + alignPts;

AddLabel(yes,
    if score >= 85 then "A+"
    else if score >= 75 then "A"
    else if score >= 65 then "A-"
    else "PASS",
    Color.BLACK);

AssignBackgroundColor(
    if score >= 85 then Color.CYAN
    else if score >= 75 then Color.GREEN
    else if score >= 65 then Color.YELLOW
    else Color.LIGHT_GRAY);
