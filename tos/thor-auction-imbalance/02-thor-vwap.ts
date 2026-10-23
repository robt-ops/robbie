#
# THOR VWAP — percent distance from session VWAP
#
# Column settings:  Aggregation = 5 min   |   Extended Hours = OFF
#
# Positive = trading above session VWAP, negative = below.
#
# This computes VWAP from typical price rather than using the `vwap`
# reserved word. The built-in is aggregation-sensitive and has reported
# extended-hours quirks; a self-anchored accumulator behaves the same way
# on every symbol and every column aggregation.
#
# STATUS: not compiled against thinkorswim. See README verification steps.

def newSession = GetDay() != GetDay()[1];

def tpv   = (high + low + close) / 3 * volume;
def cumPV = CompoundValue(1, if newSession then tpv    else cumPV[1] + tpv,    tpv);
def cumV  = CompoundValue(1, if newSession then volume else cumV[1]  + volume, volume);

def sessVwap = if cumV > 0 then cumPV / cumV else Double.NaN;

plot VwapDist = if sessVwap > 0 then (close - sessVwap) / sessVwap * 100 else Double.NaN;

VwapDist.AssignValueColor(
    if VwapDist >= 0.50 then Color.GREEN
    else if VwapDist > 0 then Color.DARK_GREEN
    else if VwapDist > -0.50 then Color.DARK_RED
    else Color.RED);
