#!/usr/bin/env python2.7
##################################################
# Gnuradio Python Flow Graph
# Title: Tetra Rx Multi
# Generated: Fri Oct 10 01:07:47 2014
##################################################

from gnuradio import analog
from gnuradio import blocks
from gnuradio import digital
from gnuradio import digital
from gnuradio import eng_notation
from gnuradio import gr
from gnuradio.eng_option import eng_option
from gnuradio.filter import firdes
from gnuradio.filter import pfb
from optparse import OptionParser
import math
import osmosdr
import threading
import time

class tetra_rx_multi(gr.top_block):

    def __init__(self):
        gr.top_block.__init__(self, "Tetra Rx Multi")

        options = self.get_options()

        ##################################################
        # Variables
        ##################################################
        self.srate_rx = srate_rx = options.sample_rate
        self.channels = srate_rx / 25000
        self.srate_channel = 36000
        self.afc_period = 1
        self.afc_gain = 1.
        self.afc_channel = options.auto_tune
        self.afc_ppm_step = options.frequency / 1.e6
        self.squelch_lvl = options.level
        self.debug = options.debug
        self.pwr_probe_channels = \
                [int(x) for x in options.debug_channels_pwr.split(',') if x]

        ##################################################
        # Rx Blocks and connections
        ##################################################
        self.src = osmosdr.source( args=options.args )
        self.src.set_sample_rate(srate_rx)
        self.src.set_center_freq(options.frequency, 0)
        self.src.set_freq_corr(options.ppm, 0)
        self.src.set_dc_offset_mode(0, 0)
        self.src.set_iq_balance_mode(0, 0)
        if options.gain is not None:
            self.src.set_gain_mode(False, 0)
            self.src.set_gain(36, 0)
        else:
            self.src.set_gain_mode(True, 0)

        out_type, dst_path = options.output.split("://", 1)
        if out_type == "udp":
            dst_ip, dst_port = dst_path.split(':', 1)

        self.pfb_channelizer_ccf = pfb.channelizer_ccf(
              self.channels,
              (firdes.root_raised_cosine(1, srate_rx, 18000, 0.35, 1024)),
              36./25.,
              100)

        self.squelch = []
        self.digital_mpsk_receiver_cc = []
        self.diff_phasor = []
        self.complex_to_arg = []
        self.multiply_const = []
        self.add_const = []
        self.float_to_uchar = []
        self.map_bits = []
        self.unpack_k_bits = []
        self.blocks_sink = []
        for ch in range(0, self.channels):
            squelch = analog.pwr_squelch_cc(self.squelch_lvl, 0.001, 0, True)
            mpsk = digital.mpsk_receiver_cc(
                    4, math.pi/4, math.pi/100.0, -0.5, 0.5, 0.25, 0.001, 2, 0.001, 0.001)
            diff_phasor = digital.diff_phasor_cc()
            complex_to_arg = blocks.complex_to_arg(1)
            multiply_const = blocks.multiply_const_vff((2./math.pi, ))
            add_const = blocks.add_const_vff((1.5, ))
            float_to_uchar = blocks.float_to_uchar()
            map_bits = digital.map_bb(([3, 2, 0, 1, 3]))
            unpack_k_bits = blocks.unpack_k_bits_bb(2)

            if out_type == 'udp':
                sink = blocks.udp_sink(gr.sizeof_gr_char, dst_ip, int(dst_port)+ch, 1472, True)
            elif out_type == 'file':
                sink = blocks.file_sink(gr.sizeof_char, dst_path % ch, False)
                sink.set_unbuffered(True)
            else:
                raise ValueError("Invalid output URL '%s'" % options.output)

            self.connect((self.pfb_channelizer_ccf, ch),
                    (squelch, 0),
                    (mpsk, 0),
                    diff_phasor,
                    complex_to_arg,
                    multiply_const,
                    add_const,
                    float_to_uchar,
                    map_bits,
                    unpack_k_bits,
                    (sink, 0))

            self.squelch.append(squelch)
            self.digital_mpsk_receiver_cc.append(mpsk)
            self.diff_phasor.append(diff_phasor)
            self.complex_to_arg.append(complex_to_arg)
            self.multiply_const.append(multiply_const)
            self.add_const.append(add_const)
            self.float_to_uchar.append(float_to_uchar)
            self.map_bits.append(map_bits)
            self.unpack_k_bits.append(unpack_k_bits)
            self.blocks_sink.append(sink)

        self.connect((self.src, 0), (self.pfb_channelizer_ccf, 0))

        ##################################################
        # channel power probes - debugging only
        ##################################################
        self.pwr_probes = []
        for ch in self.pwr_probe_channels:
            probe = analog.probe_avg_mag_sqrd_c(0, 1./self.srate_channel)
            self.pwr_probes.append(probe)
            self.connect((self.pfb_channelizer_ccf, ch), (probe, 0))
        def _probe():
            while True:
                time.sleep(1)

                s = "PWR: "
                for probe in self.pwr_probes:
                    s += "%2.2f; " % (10 * math.log10(probe.level()))
                print s
        if self.pwr_probe_channels:
            self._probe_thread = threading.Thread(target=_probe)
            self._probe_thread.daemon = True
            self._probe_thread.start()

        ##################################################
        # AFC blocks and connections
        ##################################################
        if self.afc_channel is not None:
            self.afc_demod = analog.quadrature_demod_cf(self.srate_channel/(2*math.pi))
            samp_afc = self.srate_channel*self.afc_period
            self.afc_avg = blocks.moving_average_ff(samp_afc, 1./samp_afc*self.afc_gain)
            self.freq_err = blocks.probe_signal_f()

            self.connect(
                    (self.pfb_channelizer_ccf, self.afc_channel),
                    (self.afc_demod, 0),
                    (self.afc_avg, 0),
                    (self.freq_err, 0))

            def _afc_error_probe():
                while True:
                    time.sleep(self.afc_period*2)
                    val = self.freq_err.level()
                    if val > self.afc_ppm_step * 2./3:
                        d = -1
                    elif val < -self.afc_ppm_step * 2./3:
                        d = 1
                    else:
                        continue
                    ppm = self.src.get_freq_corr() + d
                    if self.debug:
                        print "PPM: % 4d err: %f" % (ppm, val, )
                    self.src.set_freq_corr(ppm)
            _afc_err_thread = threading.Thread(target=_afc_error_probe)
            _afc_err_thread.daemon = True
            _afc_err_thread.start()

    def get_srate_rx(self):
        return self.srate_rx

    def set_srate_rx(self, srate_rx):
        self.srate_rx = srate_rx
        self.src.set_sample_rate(self.srate_rx)
        self.pfb_channelizer_ccf.set_taps((firdes.root_raised_cosine(1, self.srate_rx, 18000, 0.35, 1024)))

    def get_options(self):
        parser = OptionParser(option_class=eng_option)

        parser.add_option("-a", "--args", type="string", default="",
                help="gr-osmosdr device arguments")
        parser.add_option("-d", "--debug", action="store_true", default=False,
                help="Print out debug informations")
        parser.add_option("--debug-channels-pwr", type="string", default="",
                help="Print power value for specified channels")
        parser.add_option("-s", "--sample-rate", type="eng_float", default=1800000,
                help="set receiver sample rate (default 1800000, must be multiple of 900000)")
        parser.add_option("-f", "--frequency", type="eng_float", default=394.4e6,
                help="set receiver center frequency")
        parser.add_option("-p", "--ppm", type="eng_float", default=0.,
                help="Frequency correction as PPM")
        parser.add_option("-g", "--gain", type="eng_float", default=None,
                help="set receiver gain")
        parser.add_option("-o", "--output", type=str,
                help="output URL (eg file:///<FILE_PATH> or udp://DST_IP:PORT, use %d for channel no.")
        parser.add_option("-l", "--level", type="eng_float", default=-100.,
                help="Squelch level for channels.")
        parser.add_option("-t", "--auto-tune", type=int, default=None,
                help="Enable automatic PPM corection based on channel N")

        (options, args) = parser.parse_args()
        if len(args) != 0:
            parser.print_help()
            raise SystemExit, 1
        options.sample_rate = int(options.sample_rate)
        if options.sample_rate % 900000:
            parser.print_help()
            raise SystemExit, 1
        return (options)


if __name__ == '__main__':
    tb = tetra_rx_multi()
    tb.start()
    tb.wait()
