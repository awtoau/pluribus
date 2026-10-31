// Portable core extracted from ADI's real axi_ad9361_cmos_if.v (Xilinx variant,
// analogdevicesinc/hdl, library/axi_ad9361/xilinx/axi_ad9361_cmos_if.v, LICENSE_ADIBSD/GPL2) --
// the "frame check" + "delineation" always-blocks only, which assemble two captured half-samples
// into one 48-bit adc_data word gated by the RX_FRAME edge. The IO-serdes wrapper (ad_data_in/
// ad_data_out, IBUF/IDELAY/IDDR primitives) is vendor-specific and excluded: this module's job is
// to test whether the SAME algorithm, as plain behavioral RTL, maps onto a structurally similar
// Cyclone IV shape to any part of the DJI image's RX-side logic (#188 corpus).
module top(
  input         clk,
  input         rx_r1_mode,
  input  [1:0]  rx_frame_s,
  input  [11:0] rx_data_1_s,
  input  [11:0] rx_data_0_s,
  output [47:0] adc_data,
  output        adc_valid
);
  reg [1:0]  rx_frame;
  reg [11:0] rx_data_1;
  reg        adc_valid_p;
  reg [47:0] adc_data_p;

  always @(posedge clk) begin
    if (rx_r1_mode == 1'd1)
      rx_frame <= rx_frame_s;
    else
      rx_frame <= ~rx_frame_s;
  end

  always @(posedge clk)
    rx_data_1 <= rx_data_1_s;

  always @(posedge clk) begin
    case ({rx_r1_mode, rx_frame_s})
      3'b011: begin
        adc_valid_p <= 1'b0;
        adc_data_p[47:24] <= 24'd0;
        adc_data_p[23:0]  <= {rx_data_1_s, rx_data_0_s};
      end
      3'b000: begin
        adc_valid_p <= 1'b1;
        adc_data_p[47:24] <= {rx_data_1_s, rx_data_0_s};
        adc_data_p[23:0]  <= adc_data_p[23:0];
      end
      3'b001: begin
        adc_valid_p <= 1'b0;
        adc_data_p[47:24] <= 24'd0;
        adc_data_p[23:0]  <= {rx_data_0_s, rx_data_1};
      end
      3'b010: begin
        adc_valid_p <= 1'b1;
        adc_data_p[47:24] <= {rx_data_0_s, rx_data_1};
        adc_data_p[23:0]  <= adc_data_p[23:0];
      end
      3'b110: begin
        adc_valid_p <= 1'b1;
        adc_data_p[47:24] <= 24'd0;
        adc_data_p[23:0]  <= {rx_data_0_s, rx_data_1};
      end
      3'b101: begin
        adc_valid_p <= 1'b1;
        adc_data_p[47:24] <= 24'd0;
        adc_data_p[23:0]  <= {rx_data_1_s, rx_data_0_s};
      end
      default: begin
        adc_valid_p <= 1'b0;
        adc_data_p  <= 48'd0;
      end
    endcase
  end

  assign adc_data  = adc_data_p;
  assign adc_valid = adc_valid_p;
endmodule
