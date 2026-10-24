module top (clk, go, abort, last, busy);
  input clk;
  input go;
  input abort;
  output last;
  reg last;
  output busy;
  reg busy;
  parameter S0 = 8'd1;
  parameter S1 = 8'd2;
  parameter S2 = 8'd4;
  parameter S3 = 8'd8;
  parameter S4 = 8'd16;
  parameter S5 = 8'd32;
  parameter S6 = 8'd64;
  parameter S7 = 8'd128;
  reg [7:0] st;
  reg [7:0] ns;
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
      S7: if (abort) ns = S0; else if (go) ns = S0;
      default: ns = S0;
    endcase
  end
  always @(posedge clk) begin
    st <= ns;
    last <= (ns == S7);
    busy <= (ns != S0);
  end
endmodule
