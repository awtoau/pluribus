module top (
    input [0:0] clk,
    input [0:0] go,
    input [0:0] abort,
    output reg [0:0] last,
    output reg [0:0] busy
);
  localparam S0 = 16'd1;
  localparam S1 = 16'd2;
  localparam S2 = 16'd4;
  localparam S3 = 16'd8;
  localparam S4 = 16'd16;
  localparam S5 = 16'd32;
  localparam S6 = 16'd64;
  localparam S7 = 16'd128;
  localparam S8 = 16'd256;
  localparam S9 = 16'd512;
  localparam S10 = 16'd1024;
  localparam S11 = 16'd2048;
  localparam S12 = 16'd4096;
  localparam S13 = 16'd8192;
  localparam S14 = 16'd16384;
  localparam S15 = 16'd32768;
  reg [15:0] st;
  reg [15:0] ns;
  always @* begin
    ns = st;
    case (st)
      S0: if (abort) ns = S0; else if (go) ns = S1;
      S1: if (abort) ns = S0; else if (go) ns = S2;
      S2: if (abort) ns = S0; else if (go) ns = S3;
      S3: if (abort) ns = S0; else if (go) ns = S4;
      S4: if (abort) ns = S0; else if (go) ns = S5;
      S5: if (abort) ns = S0; else if (go) ns = S6;
      S6: if (abort) ns = S0; else if (go) ns = S7;
      S7: if (abort) ns = S0; else if (go) ns = S8;
      S8: if (abort) ns = S0; else if (go) ns = S9;
      S9: if (abort) ns = S0; else if (go) ns = S10;
      S10: if (abort) ns = S0; else if (go) ns = S11;
      S11: if (abort) ns = S0; else if (go) ns = S12;
      S12: if (abort) ns = S0; else if (go) ns = S13;
      S13: if (abort) ns = S0; else if (go) ns = S14;
      S14: if (abort) ns = S0; else if (go) ns = S15;
      S15: if (abort) ns = S0; else if (go) ns = S0;
      default: ns = S0;
    endcase
  end
  always @(posedge clk) begin
    st <= ns;
    last <= (ns == S15);
    busy <= (ns != S0);
  end
endmodule
