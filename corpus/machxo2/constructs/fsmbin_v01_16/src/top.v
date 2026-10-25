module top (
    input [0:0] clk,
    input [0:0] go,
    input [0:0] abort,
    output reg [0:0] last,
    output reg [0:0] busy
);
  localparam S0 = 4'd0;
  localparam S1 = 4'd1;
  localparam S2 = 4'd2;
  localparam S3 = 4'd3;
  localparam S4 = 4'd4;
  localparam S5 = 4'd5;
  localparam S6 = 4'd6;
  localparam S7 = 4'd7;
  localparam S8 = 4'd8;
  localparam S9 = 4'd9;
  localparam S10 = 4'd10;
  localparam S11 = 4'd11;
  localparam S12 = 4'd12;
  localparam S13 = 4'd13;
  localparam S14 = 4'd14;
  localparam S15 = 4'd15;
  reg [3:0] st;
  reg [3:0] ns;
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
