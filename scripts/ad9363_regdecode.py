#!/usr/bin/env python3
"""Generic AD9361/AD9363 register-list decoder (public register map, ADI UG-570 / Linux IIO ad9361 driver).

Input: text file(s) of `addr value` pairs (hex 0x.. or decimal; optional leading W; # comments).
Later lines win. Output: decoded channel enables, ENSM, parallel port, clock chain, RF PLLs, filters,
gain mode, TX attenuation, calibration flags. No vendor data embedded: names/formulas are from the
public ADI Linux driver (drivers/iio/adc/ad9361.c, ad9361_regs.h).

Usage: ad9363_regdecode.py [--fref HZ] [--label NAME] [--json] regs.txt [other.txt  (second file = diff)]
Log:   tmp/logs/ad9363_regdecode.log
Tags in output: V = computed from register bits per the public map; I = needs an assumption (Fref).
"""
import argparse
import json
import os
import subprocess
import sys

NAMES_TXT = (
    "000:SPI_CONF 001:MULTICHIP_SYNC_AND_TX_MON_CTRL 002:TX_ENABLE_FILTER_CTRL "
    "003:RX_ENABLE_FILTER_CTRL 004:INPUT_SELECT 005:RFPLL_DIVIDERS 006:RX_CLOCK_DATA_DELAY "
    "007:TX_CLOCK_DATA_DELAY 009:CLOCK_ENABLE 00A:BBPLL 00B:TEMP_OFFSET 00C:START_TEMP_READING "
    "00D:TEMP_SENSE2 00E:TEMPERATURE 00F:TEMP_SENSOR_CONFIG 010:PARALLEL_PORT_CONF_1 "
    "011:PARALLEL_PORT_CONF_2 012:PARALLEL_PORT_CONF_3 013:ENSM_MODE 014:ENSM_CONFIG_1 "
    "015:ENSM_CONFIG_2 016:CALIBRATION_CTRL 017:STATE 018:AUXDAC_1_WORD 019:AUXDAC_2_WORD "
    "01A:AUXDAC_1_CONFIG 01B:AUXDAC_2_CONFIG 01C:AUXADC_CLOCK_DIVIDER 01D:AUXADC_CONFIG "
    "01E:AUXADC_WORD_MSB 01F:AUXADC_LSB 020:AUTO_GPO 021:AGC_GAIN_LOCK_DELAY 022:AGC_ATTACK_DELAY "
    "023:AUXDAC_ENABLE_CTRL 024:RX_LOAD_SYNTH_DELAY 025:TX_LOAD_SYNTH_DELAY 026:EXTERNAL_LNA_CTRL "
    "027:GPO_FORCE_AND_INIT 028:GPO0_RX_DELAY 029:GPO1_RX_DELAY 02A:GPO2_RX_DELAY 02B:GPO3_RX_DELAY "
    "02C:GPO0_TX_DELAY 02D:GPO1_TX_DELAY 02E:GPO2_TX_DELAY 02F:GPO3_TX_DELAY 030:AUXDAC1_RX_DELAY "
    "031:AUXDAC1_TX_DELAY 032:AUXDAC2_RX_DELAY 033:AUXDAC2_TX_DELAY 035:CTRL_OUTPUT_POINTER "
    "036:CTRL_OUTPUT_ENABLE 037:PRODUCT_ID 03A:REFERENCE_CLOCK_CYCLES 03B:DIGITAL_IO_CTRL "
    "03C:LVDS_BIAS_CTRL 03D:LVDS_INVERT_CTRL1 03E:LVDS_INVERT_CTRL2 03F:SDM_CTRL_1 "
    "041:FRACT_BB_FREQ_WORD_1 042:FRACT_BB_FREQ_WORD_2 043:FRACT_BB_FREQ_WORD_3 "
    "044:INTEGER_BB_FREQ_WORD 045:CLOCK_CTRL 046:CP_CURRENT 047:CP_BLEED_CURRENT 048:LOOP_FILTER_1 "
    "049:LOOP_FILTER_2 04A:LOOP_FILTER_3 04B:VCO_CTRL 04C:VCO_PROGRAM_1 04D:VCO_PROGRAM_2 "
    "04E:SDM_CTRL 050:RX_SYNTH_POWER_DOWN_OVERRIDE 051:TX_SYNTH_POWER_DOWN_OVERRIDE "
    "052:RX_ANALOG_POWER_DOWN_OVERRIDE_1 053:RX_ANALOG_POWER_DOWN_OVERRIDE_2 "
    "054:RX1_ADC_POWER_DOWN_OVERRIDE 055:RX2_ADC_POWER_DOWN_OVERRIDE "
    "056:TX_ANALOG_POWER_DOWN_OVERRIDE_1 057:ANALOG_POWER_DOWN_OVERRIDE 058:MISC_POWER_DOWN_OVERRIDE "
    "05E:CH_1_OVERFLOW 05F:CH_2_OVERFLOW 060:TX_FILTER_COEF_ADDR 061:TX_FILTER_COEF_WRITE_DATA_1 "
    "062:TX_FILTER_COEF_WRITE_DATA_2 063:TX_FILTER_COEF_READ_DATA_1 064:TX_FILTER_COEF_READ_DATA_2 "
    "065:TX_FILTER_CONF 067:TX_MON_LOW_GAIN 068:TX_MON_HIGH_GAIN 069:TX_MON_DELAY "
    "06A:TX_LEVEL_THRESH 06B:TX_RSSI1 06C:TX_RSSI2 06D:TX_RSSI_LSB 06E:TPM_MODE_ENABLE "
    "06F:TX_MON_TEMP_GAIN_COEF 070:TX_MON_1_CONFIG 071:TX_MON_2_CONFIG 073:TX1_ATTEN_0 "
    "074:TX1_ATTEN_1 075:TX2_ATTEN_0 076:TX2_ATTEN_1 077:TX_ATTEN_OFFSET 078:TX_ATTEN_THRESH "
    "079:TX1_DIG_ATTEN 07C:TX2_DIG_ATTEN 07F:TX1_SYMBOL_ATTEN 080:TX2_SYMBOL_ATTEN "
    "081:TX_SYMBOL_ATTEN_CONFIG 08E:TX1_OUT_1_PHASE_CORR 08F:TX1_OUT_1_GAIN_CORR "
    "090:TX2_OUT_1_PHASE_CORR 091:TX2_OUT_1_GAIN_CORR 092:TX1_OUT_1_OFFSET_I 093:TX1_OUT_1_OFFSET_Q "
    "094:TX2_OUT_1_OFFSET_I 095:TX2_OUT_1_OFFSET_Q 096:TX1_OUT_2_PHASE_CORR 097:TX1_OUT_2_GAIN_CORR "
    "098:TX2_OUT_2_PHASE_CORR 099:TX2_OUT_2_GAIN_CORR 09A:TX1_OUT_2_OFFSET_I 09B:TX1_OUT_2_OFFSET_Q "
    "09C:TX2_OUT_2_OFFSET_I 09D:TX2_OUT_2_OFFSET_Q 09F:TX_FORCE_BITS "
    "0A0:QUAD_CAL_NCO_FREQ_PHASE_OFFSET 0A1:QUAD_CAL_CTRL 0A2:KEXP_1 0A3:KEXP_2 "
    "0A4:QUAD_SETTLE_COUNT 0A5:MAG_FTEST_THRESH 0A6:MAG_FTEST_THRESH_2 0A7:QUAD_CAL_STATUS_TX1 "
    "0A8:QUAD_CAL_STATUS_TX2 0A9:QUAD_CAL_COUNT 0AA:TX_QUAD_FULL_LMT_GAIN 0AB:SQUARER_CONFIG "
    "0AC:TX_QUAD_CAL_ATTEN 0AD:THRESH_ACCUM 0AE:TX_QUAD_LPF_GAIN 0B0:TXDAC_VDS_I 0B1:TXDAC_VDS_Q "
    "0B2:TXDAC_GN_I 0B3:TXDAC_GN_Q 0C0:TXBBF_OPAMP_A 0C1:TXBBF_OPAMP_B 0C2:TX_BBF_R1 0C3:TX_BBF_R2 "
    "0C4:TX_BBF_R3 0C5:TX_BBF_R4 0C6:TX_BBF_RP 0C7:TX_BBF_C1 0C8:TX_BBF_C2 0C9:TX_BBF_CP "
    "0CA:TX_TUNE_CTRL 0CB:TX_BBF_R2B 0CC:TX_BBF_TUNE 0D0:CONFIG0 0D1:RESISTOR 0D2:CAPACITOR "
    "0D3:LO_CM 0D6:TX_BBF_TUNE_DIVIDER 0D7:TX_BBF_TUNE_MODE 0F0:RX_FILTER_COEF_ADDR "
    "0F1:RX_FILTER_COEF_DATA_1 0F2:RX_FILTER_COEF_DATA_2 0F3:RX_FILTER_COEF_READ_DATA_1 "
    "0F4:RX_FILTER_COEF_READ_DATA_2 0F5:RX_FILTER_CONFIG 0F6:RX_FILTER_GAIN 0FA:AGC_CONFIG_1 "
    "0FB:AGC_CONFIG_2 0FC:AGC_CONFIG_3 0FD:MAX_LMT_FULL_GAIN 0FE:PEAK_WAIT_TIME 100:DIGITAL_GAIN "
    "101:AGC_LOCK_LEVEL 102:ADC_NOISE_CORRECTION_FACTOR 103:GAIN_STP_CONFIG1 "
    "104:ADC_SMALL_OVERLOAD_THRESH 105:ADC_LARGE_OVERLOAD_THRESH 106:GAIN_STP_CONFIG_2 "
    "107:SMALL_LMT_OVERLOAD_THRESH 108:LARGE_LMT_OVERLOAD_THRESH 109:RX1_MANUAL_LMT_FULL_GAIN "
    "10A:RX1_MANUAL_LPF_GAIN 10B:RX1_MANUAL_DIGITALFORCED_GAIN 10C:RX2_MANUAL_LMT_FULL_GAIN "
    "10D:RX2_MANUAL_LPF_GAIN 10E:RX2_MANUAL_DIGITALFORCED_GAIN 110:FAST_CONFIG_1 "
    "111:FAST_CONFIG_2_SETTLING_DELAY 112:FAST_ENERGY_LOST_THRESH 113:FAST_STRONGER_SIGNAL_THRESH "
    "114:FAST_LOW_POWER_THRESH 115:FAST_STRONG_SIGNAL_FREEZE 116:FAST_FINAL_OVER_RANGE_AND_OPT_GAIN "
    "117:FAST_ENERGY_DETECT_COUNT 118:FAST_AGCLL_UPPER_LIMIT 119:FAST_GAIN_LOCK_EXIT_COUNT "
    "11A:FAST_INITIAL_LMT_GAIN_LIMIT 11B:FAST_INCREMENT_TIME 120:AGC_INNER_LOW_THRESH "
    "121:LMT_OVERLOAD_COUNTERS 122:ADC_OVERLOAD_COUNTERS 123:GAIN_STP1 124:GAIN_UPDATE_COUNTER1 "
    "125:GAIN_UPDATE_COUNTER2 128:DIGITAL_SAT_COUNTER 129:OUTER_POWER_THRESHS 12A:GAIN_STP_2 "
    "12C:EXT_LNA_HIGH_GAIN 12D:EXT_LNA_LOW_GAIN 130:GAIN_TABLE_ADDRESS 131:GAIN_TABLE_WRITE_DATA1 "
    "132:GAIN_TABLE_WRITE_DATA2 133:GAIN_TABLE_WRITE_DATA3 134:GAIN_TABLE_READ_DATA1 "
    "135:GAIN_TABLE_READ_DATA2 136:GAIN_TABLE_READ_DATA3 137:GAIN_TABLE_CONFIG "
    "138:GM_SUB_TABLE_ADDRESS 139:GM_SUB_TABLE_GAIN_WRITE 13A:GM_SUB_TABLE_BIAS_WRITE "
    "13B:GM_SUB_TABLE_CTRL_WRITE 13C:GM_SUB_TABLE_GAIN_READ 13D:GM_SUB_TABLE_BIAS_READ "
    "13E:GM_SUB_TABLE_CTRL_READ 13F:GM_SUB_TABLE_CONFIG 140:WORD_ADDRESS "
    "141:GAIN_DIFF_WORDERROR_WRITE 142:GAIN_ERROR_READ 143:CONFIG 144:LNA_GAIN_DIFF_READ_BACK "
    "145:MAX_MIXER_CALIBRATION_GAIN_INDEX 146:TEMP_GAIN_COEF 147:SETTLE_TIME 148:MEASURE_DURATION "
    "149:CAL_TEMP_SENSOR_WORD 150:MEASURE_DURATION_01 151:MEASURE_DURATION_23 152:RSSI_WEIGHT_0 "
    "153:RSSI_WEIGHT_1 154:RSSI_WEIGHT_2 155:RSSI_WEIGHT_3 156:RSSI_DELAY 157:RSSI_WAIT_TIME "
    "158:RSSI_CONFIG 159:ADC_MEASURE_DURATION_01 15A:ADC_WEIGHT_0 15B:ADC_WEIGHT_1 "
    "15C:DEC_POWER_MEASURE_DURATION_0 15D:LNA_GAIN 160:CH1_ADC_POWER 161:CH1_RX_FILTER_POWER "
    "162:CH2_ADC_POWER 163:CH2_RX_FILTER_POWER 168:RX_QUAD_CAL_LEVEL 169:CALIBRATION_CONFIG_1 "
    "16A:CALIBRATION_CONFIG_2 16B:CALIBRATION_CONFIG_3 16C:CALIB_COUNT 16D:SETTLE_COUNT "
    "16E:RX_QUAD_GAIN1 16F:RX_QUAD_GAIN2 170:RX1_INPUT_A_PHASE_CORR 171:RX1_INPUT_A_GAIN_CORR "
    "172:RX2_INPUT_A_PHASE_CORR 173:RX2_INPUT_A_GAIN_CORR 174:RX1_INPUT_A_Q_OFFSET "
    "175:RX1_INPUT_A_OFFSETS 176:INPUT_A_OFFSETS_1 177:RX2_INPUT_A_OFFSETS 178:RX2_INPUT_A_I_OFFSET "
    "179:RX1_INPUT_BC_PHASE_CORR 17A:RX1_INPUT_BC_GAIN_CORR 17B:RX2_INPUT_BC_PHASE_CORR "
    "17C:RX2_INPUT_BC_GAIN_CORR 17D:RX1_INPUT_BC_Q_OFFSET 17E:RX1_INPUT_BC_OFFSETS "
    "17F:INPUT_BC_OFFSETS_1 180:RX2_INPUT_BC_OFFSETS 181:RX2_INPUT_BC_I_OFFSET 182:FORCE_BITS "
    "185:WAIT_COUNT 186:RF_DC_OFFSET_COUNT 187:RF_DC_OFFSET_CONFIG_1 188:RF_DC_OFFSET_ATTEN "
    "189:INVERT_BITS 18B:DC_OFFSET_CONFIG2 18C:RF_CAL_GAIN_INDEX 18D:SOI_THRESH "
    "190:BB_DC_OFFSET_SHIFT 191:BB_DC_OFFSET_FAST_SETTLE_SHIFT 192:BB_FAST_SETTLE_DUR "
    "193:BB_DC_OFFSET_COUNT 194:BB_DC_OFFSET_ATTEN 19A:RX1_BB_DC_WORD_I_MSB 19B:RX1_BB_DC_WORD_I_LSB "
    "19C:RX1_BB_DC_WORD_Q_MSB 19D:RX1_BB_DC_WORD_Q_LSB 19E:RX2_BB_DC_WORD_I_MSB "
    "19F:RX2_BB_DC_WORD_I_LSB 1A0:RX2_BB_DC_WORD_Q_MSB 1A1:RX2_BB_DC_WORD_Q_LSB "
    "1A2:BB_TRACK_CORR_WORD_I_MSB 1A3:BB_TRACK_CORR_WORD_I_LSB 1A4:BB_TRACK_CORR_WORD_Q_MSB "
    "1A5:BB_TRACK_CORR_WORD_Q_LSB 1A7:RX1_RSSI_SYMBOL 1A8:RX1_RSSI_PREAMBLE 1A9:RX2_RSSI_SYMBOL "
    "1AA:RX2_RSSI_PREAMBLE 1AB:SYMBOL_LSB 1AC:PREAMBLE_LSB 1AD:RX_PATH_GAIN_MSB 1AE:RX_PATH_GAIN_LSB "
    "1B0:RX_DIFF_LNA_FORCE 1B1:RX_LNA_BIAS_COARSE 1B2:RX_LNA_BIAS_FINE_0 1B3:RX_LNA_BIAS_FINE_1 "
    "1C0:RX_MIX_GM_CONFIG 1C1:RX1_MIX_GM_FORCE 1C2:RX1_MIX_GM_BIAS_FORCE 1C3:RX2_MIX_GM_FORCE "
    "1C4:RX2_MIX_GM_BIAS_FORCE 1C8:INPUT_A_MSBS 1C9:INPUT_A_RX1_I 1CA:INPUT_A_RX1_Q "
    "1CB:INPUT_A_RX2_I 1CC:INPUT_A_RX2_Q 1CD:INPUTS_BC_RX1_I 1CE:BAND1_RX1_Q 1CF:INPUTS_BC_RX2_I "
    "1D0:INPUTS_BC_RX2_Q 1D1:INPUTS_BC_MSBS 1D2:FORCE_OS_DAC 1D5:RX_MIX_LO_CM 1D6:RX_CGB_SEG_ENABLE "
    "1D7:RX_MIX_INPUTBIAS 1DB:RX_TIA_CONFIG 1DC:TIA1_C_LSB 1DD:TIA1_C_MSB 1DE:TIA2_C_LSB "
    "1DF:TIA2_C_MSB 1E0:RX1_BBF_R1A 1E1:RX2_BBF_R1A 1E2:RX1_TUNE_CTRL 1E3:RX2_TUNE_CTRL "
    "1E4:RX1_BBF_R5 1E5:RX2_BBF_R5 1E6:RX_BBF_R2346 1E7:RX_BBF_C1_MSB 1E8:RX_BBF_C1_LSB "
    "1E9:RX_BBF_C2_MSB 1EA:RX_BBF_C2_LSB 1EB:RX_BBF_C3_MSB 1EC:RX_BBF_C3_LSB 1ED:RX_BBF_CC1_CTR "
    "1EE:RX_BBF_POW_RZ_BYTE0 1EF:RX_BBF_CC2_CTR 1F0:RX_BBF_POW_RZ_BYTE1 1F1:RX_BBF_CC3_CTR "
    "1F2:RX_BBF_R5_TUNE 1F3:RX_BBF_TUNE 1F4:RX1_BBF_MAN_GAIN 1F5:RX2_BBF_MAN_GAIN "
    "1F8:RX_BBF_TUNE_DIVIDE 1F9:RX_BBF_TUNE_CONFIG 1FA:POLE_GAIN 1FB:RX_BBBW_MHZ 1FC:RX_BBBW_KHZ "
    "201:FB_DAC_CLK_DELAY1 202:FB_DAC_CLK_DELAY2 203:FLASH_SAMPLE_CLK_DELAY_3P "
    "204:FLASH_SAMPLE_CLK_DELAY_3N 205:TEST_MUX_2I 206:TEST_MUX_2Q 207:INTEGRATOR_1_RESISTANCE "
    "208:INTEGRATOR_1_CAPACITANCE 209:INTEGRATOR_23_RESISTANCE 20A:INTEGRATOR_2_RESISTANCE "
    "20B:INTEGRATOR_2_CAPACITANCE 20C:INTEGRATOR_3_RESISTANCE 20D:INTEGRATOR_3_CAPACITANCE "
    "20E:INTEGRATOR_AMP_CC 20F:INT_1_FB_DAC_NMOS_CURRENT_SOURCE "
    "210:INT_1_FB_DAC_NMOS_CASOADE_BIAS_CURRENT 211:INT_1_FB_DAC_PMOS_CURRENT_SOURCE "
    "212:INT_2_FB_DAC_NMOS_CURRENT_SOURCE 213:INT_2_FB_DAC_NMOS_CASCODE_BIAS_CURRENT "
    "214:INT_2_FB_DAC_PMOS_CURRENT_SOURCE 215:INT_3_FB_DAC_NMOS_CURRENT_SOURCE "
    "216:INT_3_FB_DAC_NMOS_CASCODE_BIAS_CURRENT 217:INT_3_FB_DAC_PMOS_CURRENT_SOURCE "
    "218:FB_DAC_BIAS_CURRENT 219:INT_1_1ST_STAGE_CURRENT 21A:INT_1_1ST_STAGE_CASCODE_CURRENT "
    "21B:INT_1_2ND_STAGE_CURRENT 21C:INTEGRATOR_2_1ST_STAGE_CURRENT "
    "21D:INT_2_1ST_STAGE_CASCODE_CURRENT 21E:INT_2_2ND_STAGE_CURRENT 21F:INT_3_1ST_STAGE_CURRENT "
    "220:INT_3_1ST_STAGE_CASCODE_CURRENT 221:INT_3_2ND_STAGE_CURRENT 222:FLASH_BIAS_CURRENT "
    "223:FLASH_LADDER_BIAS 224:FLASH_LADDER_CASCODE_CURRENT 225:FLASH_LADDER_BIAS2 226:RESET "
    "230:RX_PFD_CONFIG 231:RX_INTEGER_BYTE_0 232:RX_INTEGER_BYTE_1 233:RX_FRACT_BYTE_0 "
    "234:RX_FRACT_BYTE_1 235:RX_FRACT_BYTE_2 236:RX_FORCE_ALC 237:RX_FORCE_VCO_TUNE_0 "
    "238:RX_FORCE_VCO_TUNE_1 239:RX_ALC_VARACTOR 23A:RX_VCO_OUTPUT 23B:RX_CP_CURRENT "
    "23C:RX_CP_OFFSET 23D:RX_CP_CONFIG 23E:RX_LOOP_FILTER_1 23F:RX_LOOP_FILTER_2 "
    "240:RX_LOOP_FILTER_3 241:RX_DITHERCP_CAL 242:RX_VCO_BIAS_1 244:RX_CAL_STATUS 245:RX_VCO_CAL_REF "
    "246:RX_VCO_PD_OVERRIDES 247:RX_CP_OVERRANGE_VCO_LOCK 248:RX_VCO_LDO 249:RX_VCO_CAL "
    "24A:RX_LOCK_DETECT_CONFIG 24B:RX_CP_LEVEL_DETECT 24C:RX_DSM_SETUP_0 24D:RX_DSM_SETUP_1 "
    "24E:RX_CORRECTION_WORD0 24F:RX_CORRECTION_WORD1 250:RX_VCO_VARACTOR_CTRL_0 "
    "251:RX_VCO_VARACTOR_CTRL_1 25A:RX_FAST_LOCK_SETUP 25B:RX_FAST_LOCK_SETUP_INIT_DELAY "
    "25C:RX_FAST_LOCK_PROGRAM_ADDR 25D:RX_FAST_LOCK_PROGRAM_DATA 25E:RX_FAST_LOCK_PROGRAM_READ "
    "25F:RX_FAST_LOCK_PROGRAM_CTRL 261:RX_LO_GEN_POWER_MODE 270:TX_PFD_CONFIG 271:TX_INTEGER_BYTE_0 "
    "272:TX_INTEGER_BYTE_1 273:TX_FRACT_BYTE_0 274:TX_FRACT_BYTE_1 275:TX_FRACT_BYTE_2 "
    "276:TX_FORCE_ALC 277:TX_FORCE_VCO_TUNE_0 278:TX_FORCE_VCO_TUNE_1 279:TX_ALCVARACT_OR "
    "27A:TX_VCO_OUTPUT 27B:TX_CP_CURRENT 27C:TX_CP_OFFSET 27D:TX_CP_CONFIG 27E:TX_LOOP_FILTER_1 "
    "27F:TX_LOOP_FILTER_2 280:TX_LOOP_FILTER_3 281:TX_DITHERCP_CAL 282:TX_VCO_BIAS_1 "
    "283:TX_VCO_BIAS_2 284:TX_CAL_STATUS 285:TX_VCO_CAL_REF 286:TX_VCO_PD_OVERRIDES "
    "287:TX_CP_OVERRANGE_VCO_LOCK 288:TX_VCO_LDO 289:TX_VCO_CAL 28A:TX_LOCK_DETECT_CONFIG "
    "28B:TX_CP_LEVEL_DETECT 28C:TX_DSM_SETUP_0 28D:TX_DSM_SETUP_1 28E:TX_CORRECTION_WORD0 "
    "28F:TX_CORRECTION_WORD1 290:TX_VCO_VARACTOR_CTRL_0 291:TX_VCO_VARACTOR_CTRL_1 "
    "292:DCXO_COARSE_TUNE 293:DCXO_FINE_TUNE_HIGH 294:DCXO_FINE_TUNE_LOW 295:DCXO_CONFIG "
    "296:DCXO_TEMPCO_WRITE 297:DCXO_TEMPCO_READ 298:DCXO_TEMPCO_ADDR 299:DELTA_T_READ "
    "29A:TX_FAST_LOCK_SETUP 29B:TX_FAST_LOCK_SETUP_INIT_DELAY 29C:TX_FAST_LOCK_PROGRAM_ADDR "
    "29D:TX_FAST_LOCK_PROGRAM_DATA 29E:TX_FAST_LOCK_PROGRAM_READ 29F:TX_FAST_LOCK_PROGRAM_CTRL "
    "2A1:TX_LO_GEN_POWER_MODE 2A6:BANDGAP_CONFIG0 2A8:BANDGAP_CONFIG1 2AB:REF_DIVIDE_CONFIG_1 "
    "2AC:REF_DIVIDE_CONFIG_2 2B0:GAIN_RX1 2B1:LPF_GAIN_RX1 2B2:DIG_GAIN_RX1 2B3:FAST_ATTACK_STATE "
    "2B4:SLOW_LOOP_STATE 2B5:GAIN_RX2 2B6:LPF_GAIN_RX2 2B7:DIG_GAIN_RX2 2B8:OVRG_SIGS_RX1 "
    "2B9:OVRG_SIGS_RX2 3DF:CTRL 3F4:BIST_CONFIG 3F5:OBSERVE_CONFIG "
    "3F6:BIST_AND_DATA_PORT_TEST_CONFIG 3FC:DAC_TEST_0 3FD:DAC_TEST_1 3FE:DAC_TEST_2 "
)
NAMES = {int(t.split(":")[0], 16): t.split(":")[1] for t in NAMES_TXT.split()}

BBPLL_MOD = 2088960
RFPLL_MOD = 8388593


def repo_root():
    env = os.environ.get("PLURIBUS_REPO")
    if env and os.path.isdir(env):
        return env
    try:
        return subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                                       cwd=os.path.dirname(os.path.abspath(__file__)),
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def parse(text):
    regs = {}
    for ln in text.splitlines():
        ln = ln.split("#")[0].split(";")[0].strip()
        if not ln:
            continue
        p = ln.replace(",", " ").replace("=", " ").split()
        if p[0].upper() in ("W", "WR", "WRITE"):
            p = p[1:]
        if len(p) < 2:
            continue
        regs[int(p[0], 0)] = int(p[1], 0) & 0xFF
    return regs


def _fmt_hz(x):
    return f"{x / 1e6:.4f} MHz" if x >= 1e5 else f"{x / 1e3:.3f} kHz"


def decode(regs, fref=40e6):
    """Return list of (section, key, value-string, tag)."""
    R = lambda a: regs.get(a)
    out = []

    def add(sec, key, val, tag="V"):
        out.append((sec, key, val, tag))

    # --- channels / filter chain ---------------------------------------------------------------
    for a, nm in ((0x002, "TX"), (0x003, "RX")):
        v = R(a)
        if v is None:
            continue
        ch = (v >> 6) & 3
        on = [f"{nm}{i + 1}" for i in range(2) if ch >> i & 1]
        add("channels", f"{nm} channels enabled", ",".join(on) or "none")
        add("channels", f"{nm} mode", {3: "2-channel (2R2T class)", 1: "1-channel", 2: "1-channel", 0: "none"}[ch])
        h3 = (v >> 4) & 3
        add("filters", f"{nm} HB3/DEC3 factor", {0: 1, 1: 2, 2: 3, 3: "reserved"}[h3])
        add("filters", f"{nm} HB2 / HB1 enabled", f"{bool(v & 8)} / {bool(v & 4)}")
        f = v & 3
        add("filters", f"{nm} FIR enable/factor code", f"{f} -> x{1 << (f - 1) if f else 1} ({'FIR on' if f else 'FIR bypass'})")
    for a, nm in ((0x065, "TX FIR conf"), (0x0F5, "RX FIR conf")):
        v = R(a)
        if v is not None:
            add("filters", nm, f"taps={16 * (((v >> 5) & 7) + 1)} gain-code={(v >> 3) & 3} raw=0x{v:02X}")
    v = R(0x004)
    if v is not None:
        sel = v & 0x3F
        names_rx = {3: "RX_A_BALANCED", 0x0C: "RX_B_BALANCED", 0x30: "RX_C_BALANCED"}
        add("rf-ports", "RX input", names_rx.get(sel, f"code 0x{sel:02X}"))
        add("rf-ports", "TX output", "TX_B" if v & 0x40 else "TX_A")

    # --- ENSM / state --------------------------------------------------------------------------
    v = R(0x013)
    if v is not None:
        add("ensm", "ENSM_MODE", "FDD" if v & 1 else "TDD")
    v = R(0x014)
    if v is not None:
        fl = [n for b, n in ((7, "ENABLE_RX_DATA_PORT_FOR_CAL"), (6, "FORCE_RX_ON"), (5, "FORCE_TX_ON"),
                             (4, "ENSM_PIN_CTRL"), (3, "LEVEL_MODE"), (2, "FORCE_ALERT"), (1, "AUTO_GAIN_LOCK"),
                             (0, "TO_ALERT")) if v >> b & 1]
        add("ensm", "ENSM_CONFIG_1", f"0x{v:02X} " + "|".join(fl))
    v = R(0x015)
    if v is not None:
        fl = [n for b, n in ((7, "FDD_EXTERNAL_CTRL"), (6, "PD_RX_SYNTH"), (5, "PD_TX_SYNTH"), (4, "TXNRX_SPI_CTRL"),
                             (3, "SYNTH_EN_PIN_CTRL"), (2, "DUAL_SYNTH"), (1, "RX_SYNTH_RDY_MASK"),
                             (0, "TX_SYNTH_RDY_MASK")) if v >> b & 1]
        add("ensm", "ENSM_CONFIG_2", f"0x{v:02X} " + "|".join(fl))
    v = R(0x017)
    if v is not None:
        add("ensm", "STATE (0x017)", f"0x{v:02X} ensm_state=0x{v & 0xF:X} cal_seq_state={v >> 4}")

    # --- parallel data port --------------------------------------------------------------------
    c1, c2, c3 = R(0x010), R(0x011), R(0x012)
    if c3 is not None:
        add("data-port", "interface", "LVDS" if c3 & 0x10 else "CMOS")
        add("data-port", "data rate", "SDR" if c3 & 0x20 else "DDR")
        add("data-port", "port mode", ("single-port" if c3 & 4 else "dual-port") + ", " +
            ("half-duplex" if c3 & 8 else "full-duplex") + (", FULL_PORT" if c3 & 2 else ""))
        add("data-port", "swap ports / FD swap bits / RX=2xTX rate",
            f"{bool(c3 & 0x40)} / {bool(c3 & 1)} / {bool(c3 & 0x80)}")
    if c1 is not None:
        add("data-port", "PARALLEL_PORT_CONF_1", f"0x{c1:02X} tx_swap_iq={bool(c1 & 0x80)} rx_swap_iq={bool(c1 & 0x40)} "
            f"tx_ch_swap={bool(c1 & 0x20)} rx_ch_swap={bool(c1 & 0x10)} rx_frame_pulse={bool(c1 & 8)} "
            f"2R2T_timing={bool(c1 & 4)} inv_bus={bool(c1 & 2)} inv_clk={bool(c1 & 1)}")
    if c2 is not None:
        add("data-port", "PARALLEL_PORT_CONF_2", f"0x{c2:02X} fdd_alt_word_order={bool(c2 & 0x80)} "
            f"inv rx1/rx2/tx1/tx2={bool(c2 & 0x40)}/{bool(c2 & 0x20)}/{bool(c2 & 0x10)}/{bool(c2 & 8)} "
            f"inv_rx_frame={bool(c2 & 4)} delay_rx_data={c2 & 3}")
    for a, nm in ((0x006, "RX clk/data delay"), (0x007, "TX fb_clk/data delay")):
        if R(a) is not None:
            add("data-port", nm, f"hi-nibble={R(a) >> 4} lo-nibble={R(a) & 15}")

    # --- clocks -------------------------------------------------------------------------------
    sc = R(0x045)
    bb_ref = None
    if sc is not None:
        m, d = {0: (1, 1), 1: (1, 2), 2: (1, 4), 3: (2, 1)}[sc & 3]
        bb_ref = fref * m / d
        add("clocks", "BB ref scaler", f"x{m}/{d}; BB ref = {_fmt_hz(bb_ref)} (Fref={_fmt_hz(fref)})", "I")
    if R(0x03A) is not None:
        add("clocks", "REFERENCE_CLOCK_CYCLES (0x03A)", f"{R(0x03A)} -> Fref ~ {R(0x03A) + 1} MHz if driver convention", "I")
    bbpll = None
    if all(R(a) is not None for a in (0x041, 0x042, 0x043, 0x044)) and bb_ref:
        frac = (R(0x041) << 16) | (R(0x042) << 8) | R(0x043)
        integ = R(0x044)
        bbpll = bb_ref * (integ + frac / BBPLL_MOD)
        add("clocks", "BBPLL", f"{_fmt_hz(bbpll)} (int {integ} + {frac}/{BBPLL_MOD})", "I")
    if bbpll and R(0x00A) is not None and R(0x002) is not None and R(0x003) is not None:
        b = R(0x00A)
        adc = bbpll / (1 << (b & 7))
        dac = adc / (2 if b & 8 else 1)
        rx = R(0x003)
        tx = R(0x002)
        rdiv = ((rx >> 4) & 3) or 1
        rdiv = {0: 1, 1: 2, 2: 3, 3: 1}[(rx >> 4) & 3]
        rx_hb2 = 2 if rx & 8 else 1
        rx_hb1 = 2 if rx & 4 else 1
        rf = rx & 3
        rx_fir = (1 << (rf - 1)) if rf else 1
        rx_rate = adc / rdiv / rx_hb2 / rx_hb1 / rx_fir
        tdiv = {0: 1, 1: 2, 2: 3, 3: 1}[(tx >> 4) & 3]
        tx_hb2 = 2 if tx & 8 else 1
        tx_hb1 = 2 if tx & 4 else 1
        tf = tx & 3
        tx_fir = (1 << (tf - 1)) if tf else 1
        tx_rate = dac / tdiv / tx_hb2 / tx_hb1 / tx_fir
        add("clocks", "ADC clk / DAC clk", f"{_fmt_hz(adc)} (BBPLL/{1 << (b & 7)}) / {_fmt_hz(dac)}", "I")
        add("clocks", "RX sample rate (per channel)", _fmt_hz(rx_rate), "I")
        add("clocks", "TX sample rate (per channel)", _fmt_hz(tx_rate), "I")
        two = ((rx >> 6) & 3) == 3 or ((tx >> 6) & 3) == 3
        lvds = bool((R(0x012) or 0) & 0x10)
        if R(0x012) is not None:
            mult = (2 if two else 1) * (2 if lvds else 1)
            add("clocks", "DATA_CLK (driver convention: fs*(1+2ch)*(2 if LVDS))", _fmt_hz(rx_rate * mult), "I")

    # --- RF synthesisers --------------------------------------------------------------------
    rr = None
    if R(0x2AB) is not None and R(0x2AC) is not None and bb_ref:
        rxd = ((R(0x2AB) & 1) << 1) | (R(0x2AC) >> 7)
        txd = (R(0x2AC) >> 2) & 3
        sc_ = {0: 1.0, 1: 0.5, 2: 0.25, 3: 2.0}
        add("rf-pll", "RF ref scalers rx/tx", f"x{sc_[rxd]} / x{sc_[txd]}", "I")
        rr = (fref * sc_[rxd], fref * sc_[txd])
    if R(0x005) is not None:
        add("rf-pll", "VCO dividers rx/tx (code)", f"{R(0x005) & 15} / {R(0x005) >> 4} (LO = VCO / 2^(code+1))")
    for nm, base, di, ref in (("RX", 0x231, R(0x005) and (R(0x005) & 15), rr and rr[0]),
                              ("TX", 0x271, R(0x005) and (R(0x005) >> 4), rr and rr[1])):
        if all(R(base + k) is not None for k in range(5)):
            integ = ((R(base + 1) & 7) << 8) | R(base)
            frac = ((R(base + 4) & 0x7F) << 16) | (R(base + 3) << 8) | R(base + 2)
            s = f"N={integ}+{frac}/{RFPLL_MOD}={integ + frac / RFPLL_MOD:.5f}"
            if ref and di is not None:
                lo = ref * (integ + frac / RFPLL_MOD) / (1 << (di + 1))
                s += f" -> LO {_fmt_hz(lo)}"
            add("rf-pll", f"{nm} LO", s, "I")

    # --- analogue BB filters / calibration -------------------------------------------------
    if R(0x1FB) is not None and R(0x1FC) is not None:
        bb = R(0x1FB) + R(0x1FC) / 128.0
        add("bandwidth", "RX BB filter target (0x1FB/0x1FC)", f"{bb:.4f} MHz BB -> RF bw {2 * bb:.4f} MHz (driver: BB = RF/2)")
    if R(0x0D6) is not None and bbpll:
        div = R(0x0D6) | ((R(0x0D7) or 0) & 1) << 8
        bw = bbpll / (145036.0 * div) * 1e4 if div else 0
        add("bandwidth", "TX BBF tune divider (0x0D6/0x0D7)",
            f"{div} -> BB target ~{bw / 1e6:.3f} MHz (driver: div=ceil(BBPLL/(145036*bw/1e4)), min 0.625) -> RF ~{2 * bw / 1e6:.3f} MHz", "I")
    if R(0x016) is not None:
        v = R(0x016)
        fl = [n for b, n in ((7, "RX_BB_TUNE"), (6, "TX_BB_TUNE"), (5, "RX_QUAD"), (4, "TX_QUAD"),
                             (3, "RX_GAIN_STEP"), (2, "TXMON"), (1, "RFDC"), (0, "BBDC")) if v >> b & 1]
        add("calibration", "CALIBRATION_CTRL (last write)", f"0x{v:02X} " + "|".join(fl))

    # --- gain ----------------------------------------------------------------------------------
    v = R(0x0FA)
    if v is not None:
        md = {0: "MGC", 1: "AGC fast attack", 2: "AGC slow attack", 3: "AGC hybrid"}
        add("gain", "RX1 / RX2 gain control", f"{md[v & 3]} / {md[(v >> 2) & 3]}")
    for a, nm in ((0x073, "TX1 atten"), (0x075, "TX2 atten")):
        if R(a) is not None:
            code = R(a) | (((R(a + 1) or 0) & 1) << 8)
            add("gain", nm, f"{code} -> {code * 0.25:.2f} dB (0.25 dB/step)")
    for a, nm in ((0x109, "RX1 manual LMT/full"), (0x10C, "RX2 manual LMT/full")):
        if R(a) is not None:
            add("gain", nm, f"0x{R(a):02X}")
    return out


def render(label, rows):
    sec = None
    lines = [f"## {label}"]
    for s, k, v, t in rows:
        if s != sec:
            lines.append(f"[{s}]")
            sec = s
        lines.append(f"  {t} {k}: {v}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--fref", type=float, default=40e6, help="reference clock Hz (assumed, tag I)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    outs, regsets = [], []
    for f in a.files:
        regs = parse(open(f).read())
        regsets.append(regs)
        rows = decode(regs, a.fref)
        outs.append(json.dumps(rows) if a.json else render(os.path.basename(f), rows))
    if len(regsets) == 2:
        d = [f"  0x{r:03X} {NAMES.get(r, '?')}: {regsets[0].get(r)} vs {regsets[1].get(r)}"
             for r in sorted(set(regsets[0]) | set(regsets[1])) if regsets[0].get(r) != regsets[1].get(r)]
        outs.append("## diff (file1 vs file2)\n" + "\n".join(d))
    text = "\n\n".join(outs)
    print(text)
    logd = os.path.join(repo_root(), "tmp", "logs")
    os.makedirs(logd, exist_ok=True)
    with open(os.path.join(logd, "ad9363_regdecode.log"), "w") as fh:
        fh.write(text + "\n")


if __name__ == "__main__":
    main()
