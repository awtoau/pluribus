module top (clk, go, abort, last, busy);
  input [0:0] clk;
  input [0:0] go;
  input [0:0] abort;
  output [0:0] last;
  reg [0:0] last;
  output [0:0] busy;
  reg [0:0] busy;
  parameter S0 = 4'd0;
  parameter S1 = 4'd1;
  parameter S2 = 4'd2;
  parameter S3 = 4'd3;
  parameter S4 = 4'd4;
  parameter S5 = 4'd5;
  parameter S6 = 4'd6;
  parameter S7 = 4'd7;
  parameter S8 = 4'd8;
  parameter S9 = 4'd9;
  parameter S10 = 4'd10;
  parameter S11 = 4'd11;
  parameter S12 = 4'd12;
  parameter S13 = 4'd13;
  parameter S14 = 4'd14;
  parameter S15 = 4'd15;
  (* syn_encoding = "binary" *) reg [3:0] st;
  reg [3:0] ns;
  always @(st or go or abort) begin
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
